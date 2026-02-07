"""
GTFS Static Data Loader for CityBus
Loads stops, routes, and stop-route relationships from GTFS files.
"""

import csv
import os
from dataclasses import dataclass
from typing import Optional
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
        self._load_data()

    def _load_data(self):
        """Load all GTFS static data."""
        self._load_stops()
        self._load_routes()
        self._load_stop_routes()

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

    def _load_stop_routes(self):
        """Build stop-route relationships from trips.txt and stop_times.txt."""
        # First, load trip_id -> route_id mapping
        trip_routes: dict[str, str] = {}
        trips_file = os.path.join(self.gtfs_dir, "trips.txt")
        with open(trips_file, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                trip_routes[row["trip_id"].strip()] = row["route_id"].strip()

        # Then, build stop-route relationships from stop_times.txt
        stop_times_file = os.path.join(self.gtfs_dir, "stop_times.txt")
        with open(stop_times_file, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                trip_id = row["trip_id"].strip()
                stop_id = row["stop_id"].strip()
                route_id = trip_routes.get(trip_id)
                
                if route_id:
                    if stop_id not in self.stop_routes:
                        self.stop_routes[stop_id] = set()
                    self.stop_routes[stop_id].add(route_id)
                    
                    if route_id not in self.route_stops:
                        self.route_stops[route_id] = set()
                    self.route_stops[route_id].add(stop_id)

    def search_stops(self, query: str, limit: int = 5) -> list[Stop]:
        """Fuzzy search for stops by name."""
        if not query:
            return []
        
        # Create a list of (stop_id, stop_name) for matching
        stop_names = [(s.stop_id, s.stop_name) for s in self.stops.values()]
        
        # Use rapidfuzz to find matches
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
