"""
GTFS Static Data Loader for CityBus
Loads stops, routes, and stop-route relationships from GTFS files.
"""

import csv
import os
from dataclasses import dataclass
from typing import Optional
from datetime import datetime
from rapidfuzz import fuzz, process

GTFS_DIR = os.path.join(os.path.dirname(__file__), "data")


@dataclass
class Stop:
    stop_id: str
    stop_code: str
    stop_name: str
    stop_lat: float
    stop_lon: float


@dataclass
class Route:
    route_id: str
    route_short_name: str
    route_long_name: str
    route_color: str


class GTFSLoader:
    def __init__(self, gtfs_dir: str = GTFS_DIR):
        self.gtfs_dir = gtfs_dir
        self.stops: dict[str, Stop] = {}
        self.routes: dict[str, Route] = {}
        self.stop_routes: dict[str, set[str]] = {}  # stop_id -> set of route_ids
        self.route_stops: dict[str, set[str]] = {}  # route_id -> set of stop_ids
        # Schedule data
        self.calendar: dict[str, dict] = {}  # service_id -> {monday: 1, ...}
        self.trips: dict[str, dict] = {}  # trip_id -> {route_id, service_id, headsign}
        self.stop_times: dict[str, list[tuple]] = {}  # stop_id -> [(seconds, trip_id), ...]
        self._load_data()

    def _load_data(self):
        """Load all GTFS static data."""
        self._load_stops()
        self._load_routes()
        self._load_calendar()
        self._load_trips_and_times()

    def _load_stops(self):
        """Load stops from stops.txt."""
        stops_file = os.path.join(self.gtfs_dir, "stops.txt")
        with open(stops_file, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                stop = Stop(
                    stop_id=row["stop_id"].strip(),
                    stop_code=row.get("stop_code", row["stop_id"]).strip(),
                    stop_name=row["stop_name"].strip(),
                    stop_lat=float(row["stop_lat"]),
                    stop_lon=float(row["stop_lon"]),
                )
                self.stops[stop.stop_id] = stop

    def _load_routes(self):
        """Load routes from routes.txt."""
        routes_file = os.path.join(self.gtfs_dir, "routes.txt")
        with open(routes_file, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                route = Route(
                    route_id=row["route_id"].strip(),
                    route_short_name=row.get("route_short_name", "").strip(),
                    route_long_name=row.get("route_long_name", "").strip(),
                    route_color=row.get("route_color", "000000").strip(),
                )
                self.routes[route.route_id] = route

    def _load_calendar(self):
        """Load service calendar."""
        cal_file = os.path.join(self.gtfs_dir, "calendar.txt")
        if not os.path.exists(cal_file):
            return
            
        with open(cal_file, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                self.calendar[row["service_id"]] = {
                    "monday": int(row["monday"]),
                    "tuesday": int(row["tuesday"]),
                    "wednesday": int(row["wednesday"]),
                    "thursday": int(row["thursday"]),
                    "friday": int(row["friday"]),
                    "saturday": int(row["saturday"]),
                    "sunday": int(row["sunday"]),
                    "start_date": row["start_date"],
                    "end_date": row["end_date"],
                }

    def _load_trips_and_times(self):
        """Load trips and stop times."""
        # Load trips
        trips_file = os.path.join(self.gtfs_dir, "trips.txt")
        with open(trips_file, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                self.trips[row["trip_id"]] = {
                    "route_id": row["route_id"],
                    "service_id": row["service_id"],
                    "headsign": row.get("trip_headsign", "")
                }
        
        # Load stop times
        stop_times_file = os.path.join(self.gtfs_dir, "stop_times.txt")
        with open(stop_times_file, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                stop_id = row["stop_id"]
                trip_id = row["trip_id"]
                arrival_time = row["arrival_time"]
                
                # Convert HH:MM:SS to seconds past midnight
                h, m, s = map(int, arrival_time.split(":"))
                seconds = h * 3600 + m * 60 + s
                
                if stop_id not in self.stop_times:
                    self.stop_times[stop_id] = []
                self.stop_times[stop_id].append((seconds, trip_id))

        # Sort all stop times by time
        for stop_id in self.stop_times:
            self.stop_times[stop_id].sort(key=lambda x: x[0])
            
            # Populate stop_routes and route_stops (legacy support)
            for _, trip_id in self.stop_times[stop_id]:
                trip = self.trips.get(trip_id)
                if trip:
                    route_id = trip["route_id"]
                    if stop_id not in self.stop_routes:
                        self.stop_routes[stop_id] = set()
                    self.stop_routes[stop_id].add(route_id)
                    if route_id not in self.route_stops:
                        self.route_stops[route_id] = set()
                    self.route_stops[route_id].add(stop_id)

    def get_scheduled_arrivals(self, stop_id: str, day_of_week: str, current_seconds: int, duration_seconds: int = None) -> list[dict]:
        """Get scheduled arrivals for a stop."""
        if stop_id not in self.stop_times:
            return []
            
        arrivals = []
        # Handle day wrap-around (e.g. 25:00:00) by checking up to 48 hours?
        # For simple bot, just check today's schedule from current time
        
        for seconds, trip_id in self.stop_times[stop_id]:
            # Filter by time (today)
            if seconds < current_seconds:
                continue
            if duration_seconds and seconds > (current_seconds + duration_seconds):
                break
                
            trip = self.trips.get(trip_id)
            if not trip:
                continue
                
            # Check calendar
            service_id = trip["service_id"]
            service = self.calendar.get(service_id)
            if not service or service.get(day_of_week) != 1:
                continue
            
            # Check date range (if available)
            if "start_date" in service and "end_date" in service:
                today = datetime.now().strftime("%Y%m%d")
                if not (service["start_date"] <= today <= service["end_date"]):
                    continue
                
            # Add to results
            arrivals.append({
                "time_seconds": seconds,
                "route_id": trip["route_id"],
                "headsign": trip["headsign"]
            })
            
        return arrivals

    def search_stops(self, query: str, limit: int = 5) -> list[Stop]:
        """Fuzzy search for stops by name."""
        if not query:
            return []
        
        # 1. Exact/Partial match on stop_id or stop_code (case-insensitive)
        query_lower = query.lower()
        exact_matches = []
        for stop in self.stops.values():
            if (query_lower in stop.stop_id.lower() or 
                query_lower in stop.stop_code.lower()):
                exact_matches.append(stop)
        
        # If we have exact matches, return them (prioritize short matches)
        if exact_matches:
            exact_matches.sort(key=lambda s: len(s.stop_id))
            return exact_matches[:limit]
        
        # 2. Fuzzy search on stop_name
        stop_names = [(s.stop_id, s.stop_name) for s in self.stops.values()]
        results = process.extract(
            query,
            {s[0]: s[1] for s in stop_names},
            scorer=fuzz.WRatio,
            limit=limit,
        )
        
        return [self.stops[r[2]] for r in results if r[1] > 50]

    def get_routes_for_stop(self, stop_id: str) -> list[Route]:
        """Get all routes that serve a stop."""
        route_ids = self.stop_routes.get(stop_id, set())
        return [self.routes[rid] for rid in route_ids if rid in self.routes]

    def get_stop(self, stop_id: str) -> Optional[Stop]:
        """Get a stop by ID."""
        return self.stops.get(stop_id)

    def get_route(self, route_id: str) -> Optional[Route]:
        """Get a route by ID."""
        return self.routes.get(route_id)


# Global instance for convenience
_loader: Optional[GTFSLoader] = None


def get_loader() -> GTFSLoader:
    """Get or create the GTFS loader singleton."""
    global _loader
    if _loader is None:
        _loader = GTFSLoader()
    return _loader


def search_stops(query: str, limit: int = 5) -> list[Stop]:
    """Search for stops by name."""
    return get_loader().search_stops(query, limit)


def get_routes_for_stop(stop_id: str) -> list[Route]:
    """Get all routes serving a stop."""
    return get_loader().get_routes_for_stop(stop_id)


if __name__ == "__main__":
    # Test the loader
    loader = get_loader()
    print(f"Loaded {len(loader.stops)} stops and {len(loader.routes)} routes")
    
    # Test search
    results = search_stops("Walmart")
    print("\nSearch 'Walmart':")
    for stop in results:
        routes = get_routes_for_stop(stop.stop_id)
        route_names = [r.route_short_name for r in routes]
        print(f"  {stop.stop_name} ({stop.stop_id}) - Routes: {', '.join(route_names)}")
