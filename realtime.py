"""
GTFS-Realtime Data Fetcher for CityBus
Fetches and parses real-time arrival predictions from CityBus GTFS-RT feeds.
"""

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import requests
from google.transit import gtfs_realtime_pb2

# CityBus GTFS-RT feed URLs
TRIP_UPDATES_URL = "https://bus.gocitybus.com/GTFSRT/GTFS_TripUpdates.pb"
VEHICLE_POSITIONS_URL = "https://bus.gocitybus.com/GTFSRT/GTFS_VehiclePositions.pb"
SERVICE_ALERTS_URL = "https://bus.gocitybus.com/GTFSRT/GTFS_ServiceAlerts.pb"


@dataclass
class Arrival:
    route_id: str
    trip_id: str
    stop_id: str
    arrival_time: Optional[datetime]
    delay_seconds: int
    minutes_until: int  # Minutes until arrival
    trip_headsign: str = ""  # Where the bus is heading


def fetch_trip_updates() -> gtfs_realtime_pb2.FeedMessage:
    """Fetch the trip updates feed from CityBus."""
    response = requests.get(TRIP_UPDATES_URL, timeout=10)
    response.raise_for_status()
    
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(response.content)
    return feed


def get_arrivals_for_stop(stop_id: str, route_id: Optional[str] = None) -> list[Arrival]:
    """
    Get upcoming arrivals for a specific stop.
    
    Args:
        stop_id: The GTFS stop ID to get arrivals for
        route_id: Optional route ID to filter by
    
    Returns:
        List of Arrival objects sorted by arrival time
    """
    try:
        feed = fetch_trip_updates()
    except Exception as e:
        print(f"Error fetching trip updates: {e}")
        return []
    
    arrivals: list[Arrival] = []
    current_time = int(time.time())
    
    for entity in feed.entity:
        if not entity.HasField("trip_update"):
            continue
        
        trip_update = entity.trip_update
        trip_route_id = trip_update.trip.route_id
        trip_id = trip_update.trip.trip_id
        
        # Filter by route if specified
        if route_id and trip_route_id != route_id:
            continue
        
        for stop_time_update in trip_update.stop_time_update:
            if stop_time_update.stop_id != stop_id:
                continue
            
            # Get arrival time
            arrival_timestamp = None
            delay = 0
            
            if stop_time_update.HasField("arrival"):
                if stop_time_update.arrival.HasField("time"):
                    arrival_timestamp = stop_time_update.arrival.time
                if stop_time_update.arrival.HasField("delay"):
                    delay = stop_time_update.arrival.delay
            elif stop_time_update.HasField("departure"):
                if stop_time_update.departure.HasField("time"):
                    arrival_timestamp = stop_time_update.departure.time
                if stop_time_update.departure.HasField("delay"):
                    delay = stop_time_update.departure.delay
            
            if arrival_timestamp is None:
                continue
            
            # Calculate minutes until arrival
            minutes_until = (arrival_timestamp - current_time) // 60
            
            # Skip arrivals in the past or too far in the future (2 hours)
            if minutes_until < 0 or minutes_until > 120:
                continue
            
            # Get trip headsign
            trip_headsign = ""
            if trip_update.trip.HasField("trip_headsign"):
                trip_headsign = trip_update.trip.trip_headsign
            
            arrivals.append(Arrival(
                route_id=trip_route_id,
                trip_id=trip_id,
                stop_id=stop_id,
                arrival_time=datetime.fromtimestamp(arrival_timestamp),
                delay_seconds=delay,
                minutes_until=minutes_until,
                trip_headsign=trip_headsign,
            ))
    
    # Sort by minutes until arrival
    arrivals.sort(key=lambda a: a.minutes_until)
    return arrivals


def get_next_arrival(stop_id: str, route_id: str) -> Optional[Arrival]:
    """Get the next arrival for a specific stop and route."""
    arrivals = get_arrivals_for_stop(stop_id, route_id)
    return arrivals[0] if arrivals else None


def format_arrival_message(arrival: Arrival, route_name: str = "") -> str:
    """Format an arrival as a user-friendly message."""
    if arrival.minutes_until == 0:
        time_str = "arriving now"
    elif arrival.minutes_until == 1:
        time_str = "1 minute"
    else:
        time_str = f"{arrival.minutes_until} minutes"
    
    route_str = route_name or arrival.route_id
    
    # Add destination if available
    destination = f" → {arrival.trip_headsign}" if arrival.trip_headsign else ""
    
    if arrival.delay_seconds > 60:
        delay_min = arrival.delay_seconds // 60
        return f"🚌 Route {route_str}{destination}: {time_str} (delayed {delay_min}min)"
    elif arrival.delay_seconds < -60:
        early_min = abs(arrival.delay_seconds) // 60
        return f"🚌 Route {route_str}{destination}: {time_str} ({early_min}min early)"
    else:
        return f"🚌 Route {route_str}{destination}: {time_str}"


if __name__ == "__main__":
    # Test the realtime fetcher
    print("Testing GTFS-RT fetcher...")
    
    # Test with CityBus Center stop
    stop_id = "BUS215"
    arrivals = get_arrivals_for_stop(stop_id)
    
    print(f"\nArrivals at {stop_id} (CityBus Center):")
    if arrivals:
        for arrival in arrivals[:5]:
            print(f"  {format_arrival_message(arrival)}")
    else:
        print("  No upcoming arrivals found")
