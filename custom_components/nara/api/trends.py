import os
import sys
import time
import json
from collections import defaultdict
from datetime import datetime

try:
    from zoneinfo import ZoneInfo
except ImportError:
    import pytz
    ZoneInfo = pytz.timezone

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from nara import NaraAPI

class TrendsHelper:
    def __init__(self, email, password):
        self.api = NaraAPI(email, password)
        
    def _parse_volume(self, track, prefix):
        num = track.get(f"{prefix}Num")
        exp = track.get(f"{prefix}Exp", 0)
        if num is None:
            return 0.0
        return num / (10 ** exp)

    def _is_daytime(self, ts_ms, tz_str):
        if not tz_str: tz_str = "UTC"
        try:
            dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=ZoneInfo(tz_str))
            return 6 <= dt.hour < 18
        except:
            # Fallback to UTC if timezone parsing fails
            dt = datetime.utcfromtimestamp(ts_ms / 1000.0)
            return 6 <= dt.hour < 18

    def get_trends(self):
        now_ms = int(time.time() * 1000)
        day_ms = 24 * 60 * 60 * 1000
        
        windows = {
            "1_day": now_ms - day_ms,
            "7_days": now_ms - (7 * day_ms),
            "14_days": now_ms - (14 * day_ms)
        }
        
        print("Fetching historical data from Nara Baby...")
        tracks = self.api.get_data()
        
        # Sort all tracks chronologically to easily calculate gaps
        sorted_tracks = sorted(tracks.values(), key=lambda t: t.get("beginDt", 0))
        
        results = {}
        for w_name, w_start in windows.items():
            window_tracks = [t for t in sorted_tracks if t.get("beginDt", 0) >= w_start]
            results[w_name] = self._calculate_metrics(window_tracks)
            
        return results
        
    def _calculate_metrics(self, tracks):
        stats = {
            "sleep": {
                "total_duration_ms": 0, "day_duration_ms": 0, "longest_duration_ms": 0,
                "nap_count": 0, "nap_duration_ms": 0, 
                "wake_windows": [], "last_end_ms": None
            },
            "feed": {
                "count": 0, "total_bf_ms": 0, "day_bf_ms": 0, "night_bf_ms": 0, 
                "bf_sessions": 0, "bottle_vol_floz": 0, "bottle_count": 0,
                "feed_intervals": [], "last_start_ms": None
            },
            "pump": {
                "count": 0, "total_duration_ms": 0, "total_vol_floz": 0
            },
            "diaper": {
                "total": 0, "day_count": 0, "night_count": 0, "pee": 0, "poop": 0
            }
        }
        
        for track in tracks:
            t = track.get("type")
            begin = track.get("beginDt", 0)
            end = track.get("endDt", begin)
            dur = end - begin
            tz = track.get("tz", "UTC")
            daytime = self._is_daytime(begin, tz)
            
            if t == "SLEEP":
                stats["sleep"]["total_duration_ms"] += dur
                stats["sleep"]["longest_duration_ms"] = max(stats["sleep"]["longest_duration_ms"], dur)
                
                if daytime:
                    stats["sleep"]["day_duration_ms"] += dur
                    stats["sleep"]["nap_count"] += 1
                    stats["sleep"]["nap_duration_ms"] += dur
                    
                # Wake window (gap from last sleep END to this sleep BEGIN)
                if stats["sleep"]["last_end_ms"] is not None:
                    gap = begin - stats["sleep"]["last_end_ms"]
                    if gap > 0:
                        stats["sleep"]["wake_windows"].append(gap)
                stats["sleep"]["last_end_ms"] = end
                
            elif t == "FEED":
                stats["feed"]["count"] += 1
                f_type = track.get("feedType")
                
                # Gap between feeds (start-to-start)
                if stats["feed"]["last_start_ms"] is not None:
                    gap = begin - stats["feed"]["last_start_ms"]
                    if gap > 0:
                        stats["feed"]["feed_intervals"].append(gap)
                stats["feed"]["last_start_ms"] = begin
                
                if f_type == "BREAST":
                    bf_dur = track.get("breastLeftDuration", 0) + track.get("breastRightDuration", 0)
                    stats["feed"]["total_bf_ms"] += bf_dur
                    stats["feed"]["bf_sessions"] += 1
                    if daytime:
                        stats["feed"]["day_bf_ms"] += bf_dur
                    else:
                        stats["feed"]["night_bf_ms"] += bf_dur
                        
                elif f_type == "BOTTLE":
                    vol = self._parse_volume(track, "bottleVolume")
                    if vol > 0:
                        stats["feed"]["bottle_vol_floz"] += vol
                        stats["feed"]["bottle_count"] += 1
                        
            elif t == "PUMP":
                stats["pump"]["count"] += 1
                stats["pump"]["total_duration_ms"] += dur
                stats["pump"]["total_vol_floz"] += (self._parse_volume(track, "breastLeftVolume") + self._parse_volume(track, "breastRightVolume"))
                
            elif t == "DIAPER":
                stats["diaper"]["total"] += 1
                if daytime:
                    stats["diaper"]["day_count"] += 1
                else:
                    stats["diaper"]["night_count"] += 1
                    
                if track.get("diaperTypePee"): stats["diaper"]["pee"] += 1
                if track.get("diaperTypePoop"): stats["diaper"]["poop"] += 1
                
        return stats

    def _fmt_ms(self, ms):
        if ms == 0 or not ms: return "0h 0m"
        mins = int(ms) // 60000
        hrs = mins // 60
        rem_mins = mins % 60
        return f"{hrs}h {rem_mins}m"
        
    def _avg(self, ms_list):
        if not ms_list: return 0
        return sum(ms_list) / len(ms_list)

    def print_report(self, metric=True):
        trends = self.get_trends()
        
        for w in ["1_day", "7_days", "14_days"]:
            d = trends[w]
            print(f"\n======================================")
            print(f" {w.upper().replace('_', ' ')} ADVANCED TRENDS")
            print(f"======================================")
            
            # --- FEED ---
            fd = d['feed']
            avg_bf_len = self._fmt_ms(fd['total_bf_ms'] / max(1, fd['bf_sessions']))
            avg_feed_gap = self._fmt_ms(self._avg(fd['feed_intervals']))
            
            # Convert to mL if metric is True
            conversion = 29.5735 if metric else 1
            unit = "mL" if metric else "oz"
            
            total_bottle_vol = round(fd['bottle_vol_floz'] * conversion, 1)
            avg_bottle = round((fd['bottle_vol_floz'] / max(1, fd['bottle_count'])) * conversion, 1) if fd['bottle_count'] > 0 else 0
            
            print(f"\n[ FEEDING ] - {fd['count']} sessions")
            print(f"  Breastfeeding:")
            print(f"    - Total BF hours: {self._fmt_ms(fd['total_bf_ms'])}")
            print(f"    - Daytime BF:     {self._fmt_ms(fd['day_bf_ms'])}")
            print(f"    - Nighttime BF:   {self._fmt_ms(fd['night_bf_ms'])}")
            print(f"    - Avg BF session: {avg_bf_len}")
            print(f"  Bottle:")
            print(f"    - Total amount:   {total_bottle_vol} {unit}")
            print(f"    - Avg size:       {avg_bottle} {unit}")
            print(f"  Timing:")
            print(f"    - Avg time btwn:  {avg_feed_gap}")
            
            # --- PUMP ---
            pd = d['pump']
            total_pump_vol = round(pd['total_vol_floz'] * conversion, 1)
            print(f"\n[ PUMPING ] - {pd['count']} sessions")
            print(f"  - Amount pumped:    {total_pump_vol} {unit}")
            print(f"  - Total pump hours: {self._fmt_ms(pd['total_duration_ms'])}")
            
            # --- DIAPER ---
            dd = d['diaper']
            print(f"\n[ DIAPERS ] - {dd['total']} total")
            print(f"  - Daytime diapers:   {dd['day_count']}")
            print(f"  - Nighttime diapers: {dd['night_count']}")
            print(f"  - (Pee: {dd['pee']} | Poop: {dd['poop']})")
            
            # --- SLEEP ---
            sd = d['sleep']
            avg_nap_len = self._fmt_ms(sd['nap_duration_ms'] / max(1, sd['nap_count']))
            avg_wake_win = self._fmt_ms(self._avg(sd['wake_windows']))
            
            print(f"\n[ SLEEP ]")
            print(f"  - Total sleep:      {self._fmt_ms(sd['total_duration_ms'])}")
            print(f"  - Daytime sleep:    {self._fmt_ms(sd['day_duration_ms'])}")
            print(f"  - Longest sleep:    {self._fmt_ms(sd['longest_duration_ms'])}")
            print(f"  Naps:")
            print(f"    - Daytime naps:   {sd['nap_count']} sessions")
            print(f"    - Avg nap length: {avg_nap_len}")
            print(f"  Timing:")
            print(f"    - Avg wake window: {avg_wake_win}")

if __name__ == "__main__":
    email = os.environ.get("NARA_EMAIL", "your_email@domain.com")
    password = os.environ.get("NARA_PASSWORD", "your_password")
    if email == "your_email@domain.com":
        print("Please set NARA_EMAIL and NARA_PASSWORD environment variables.")
        sys.exit(1)
        
    helper = TrendsHelper(email=email, password=password)
    helper.print_report()
