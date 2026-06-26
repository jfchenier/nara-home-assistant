import requests
import json
import os
import time
import uuid

class NaraAPI:
    API_KEY = "AIzaSyApsJ5h5-JCjp9SJvWbHG4Fxq8NbxDW0EQ"
    DB_URL = "https://amazing-ripple-221320.firebaseio.com"
    CF_URL = "https://us-central1-amazing-ripple-221320.cloudfunctions.net/app"
    TIMERS_FILE = ".nara_timers.json"
    
    def __init__(self, email, password):
        """
        Initializes the NaraAPI client and authenticates with Firebase.
        
        Args:
            email (str): The email address for the Nara Baby account.
            password (str): The password for the Nara Baby account.
        """
        self.email = email
        self.password = password
        self.id_token = None
        self.uid = None
        self.family_key = None
        self.child_key = None
        self._authenticate()
        
    def _authenticate(self):
        """
        Authenticates with Firebase Identity Toolkit and retrieves the user's
        ID token, local UID, family key, and default child key.
        """
        print(f"Authenticating as {self.email}...")
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={self.API_KEY}"
        res = requests.post(url, json={
            'email': self.email,
            'password': self.password,
            'returnSecureToken': True
        })
        
        if res.status_code != 200:
            raise Exception(f"Login failed: {res.text}")
            
        data = res.json()
        self.id_token = data['idToken']
        self.uid = data['localId']
        
        # Fetch family key
        fam_res = requests.get(f"{self.DB_URL}/userz/{self.uid}/familyKeyz.json?auth={self.id_token}")
        if fam_res.status_code == 200 and fam_res.json():
            families = list(fam_res.json().keys())
            if families:
                self.family_key = families[0]
        else:
            raise Exception("Could not retrieve family keys.")
            
        # Try to find a child key by pulling the tracks using the cloud function
        tracks = self.get_data()
        for t in tracks.values():
            if "childKey" in t:
                self.child_key = t["childKey"]
                break
                
        print(f"Authenticated successfully! UID: {self.uid}, Family: {self.family_key}, Child: {self.child_key}")

    def login(self):
        self._authenticate()

    def _do_request(self, method, url, **kwargs):
        import re
        res = requests.request(method, url, **kwargs)
        if res.status_code == 401:
            print("Token expired, re-authenticating...")
            self.login()
            url = re.sub(r'auth=[^&]+', f'auth={self.id_token}', url)
            if 'headers' in kwargs and 'Authorization' in kwargs['headers']:
                kwargs['headers']['Authorization'] = f"Bearer {self.id_token}"
            res = requests.request(method, url, **kwargs)
        res.raise_for_status()
        return res

    def get_data(self):
        """
        Fetches all the recent activities from the Nara cloud functions sync endpoint.
        """
        payload = {
            "data": {
                "action": "/family/trackz/sync2",
                "familyKey": self.family_key,
                "prevSyncKey": None
            }
        }
        res = self._do_request("POST", self.CF_URL, json=payload, headers={"Authorization": f"Bearer {self.id_token}"})
        
        data = res.json()
        tracks = data.get("result", {}).get("trackz", {})
        return tracks

    def stream_activities(self, callback):
        """
        Connects to the Firebase Realtime Database SSE stream and listens for new activities in real-time.
        This blocks the current thread indefinitely.
        
        Args:
            callback (function): A function that takes a dictionary representing the new/updated activity.
        """
        # We use orderBy="updateDt" & startAt=<now> so we only receive new events
        # from the moment the stream connects, bypassing the entire historical dataset.
        now_ms = int(time.time() * 1000)
        url = f"{self.DB_URL}/familyz/{self.family_key}/trackz.json?auth={self.id_token}&orderBy=\"updateDt\"&startAt={now_ms}"
        headers = {'Accept': 'text/event-stream'}
        
        res = requests.get(url, headers=headers, stream=True)
        if res.status_code == 401:
            print("SSE Stream got 401, re-authenticating...")
            self.login()
            url = f"{self.DB_URL}/familyz/{self.family_key}/trackz.json?auth={self.id_token}&orderBy=\"updateDt\"&startAt={now_ms}"
            res = requests.get(url, headers=headers, stream=True)
            
        if res.status_code != 200:
            raise Exception(f"Failed to connect to stream: {res.text}")
            
        current_event = None
        for line in res.iter_lines(chunk_size=1):
            if not line:
                continue
                
            decoded_line = line.decode('utf-8')
            
            if decoded_line.startswith("event: "):
                current_event = decoded_line.replace("event: ", "")
            elif decoded_line.startswith("data: "):
                data_str = decoded_line.replace("data: ", "")
                if data_str == "null":
                    continue
                    
                try:
                    payload = json.loads(data_str)
                    
                    if current_event in ["put", "patch"]:
                        data_val = payload.get("data")
                        path_val = payload.get("path")
                        
                        if data_val is None:
                            continue
                            
                        # If it's the initial payload, the path is "/" and data is a dict of the matched items.
                        if path_val == "/":
                            if isinstance(data_val, dict):
                                for key, track in data_val.items():
                                    if isinstance(track, dict):
                                        track["key"] = key
                                        callback(track)
                        elif path_val.startswith("/"):
                            # Path could be "/-OvkXYZ" or deeper like "/-OvkXYZ/breastLeftBeginDt"
                            parts = path_val.strip("/").split("/")
                            track_id = parts[0]
                            
                            if len(parts) == 1:
                                # Full track update or partial patch at track root
                                if isinstance(data_val, dict):
                                    data_val["key"] = track_id
                                    callback(data_val)
                                elif data_val is None:
                                    # Track was deleted!
                                    callback({"key": track_id, "_deleted": True})
                            elif len(parts) == 2:
                                # Deep update for a specific field, e.g. "/-OvkXYZ/endDt"
                                field_name = parts[1]
                                payload_dict = {field_name: data_val, "key": track_id}
                                callback(payload_dict)
                                
                except json.JSONDecodeError:
                    pass

    def _generate_id(self):
        """Generates a UUID without dashes, used for Firebase keys and sync groups."""
        return str(uuid.uuid4()).replace("-", "")

    def _get_local_timezone(self):
        """Get the local timezone as an IANA timezone string."""
        try:
            import tzlocal
            return tzlocal.get_localzone_name()
        except Exception:
            return "UTC"

    def _push_payload(self, payload, track_id=None):
        """
        Pushes a raw JSON payload to the Nara Baby Firebase database.
        
        This method writes to both the persistent Realtime Database (trackz)
        and the Cloud Function sync queue (instreamz) to ensure the mobile app
        receives real-time updates.
        
        Args:
            payload (dict): The complete Firebase activity payload.
            track_id (str, optional): An existing track ID to edit an activity.
                If None, a new track ID is generated.
                
        Returns:
            str: The track ID (key) of the logged activity.
        """
        if track_id is None:
            track_id = "-Ovk" + self._generate_id()[:16]
        payload["key"] = track_id
        if "childKey" not in payload and self.child_key:
            payload["childKey"] = self.child_key
        payload["familyKey"] = self.family_key
        
        # 1. Write the persistent data to Realtime DB (failsafe)
        path_trackz = f"/familyz/{self.family_key}/trackz/{track_id}.json"
        self._do_request("PUT", f"{self.DB_URL}{path_trackz}?auth={self.id_token}", json=payload)
            
        # 2. Write to instreamz to trigger real-time app sync via cloud functions
        sync_group = self._generate_id()
        path_instreamz = f"/instreamz/familyz/{self.family_key}/trackz/{self.uid}/{sync_group}/value/{track_id}.json"
        self._do_request("PUT", f"{self.DB_URL}{path_instreamz}?auth={self.id_token}", json=payload)
        
        return track_id

    def get_track(self, track_id):
        """
        Fetches a specific track from Firebase.
        """
        path = f"/familyz/{self.family_key}/trackz/{track_id}.json"
        res = self._do_request("GET", f"{self.DB_URL}{path}?auth={self.id_token}")
        if res.status_code == 200:
            track = res.json()
            if track:
                track["key"] = track_id
            return track
        return None

    def patch_activity(self, track_id, updates):
        """
        Applies a partial update to an existing track in Realtime DB,
        then pushes the full updated track to the instreamz sync queue.
        """
        path_trackz = f"/familyz/{self.family_key}/trackz/{track_id}.json"
        
        # We MUST send None values to PATCH so Firebase deletes those fields
        self._do_request("PATCH", f"{self.DB_URL}{path_trackz}?auth={self.id_token}", json=updates)
        
        # We need to write to instreamz to trigger the cloud functions too.
        # instreamz expects the FULL object to be pushed, not just the patch!
        # Fetch the complete updated track and push to instreamz
        full_track = self.get_track(track_id)
        if full_track:
            # We don't want None fields in the fetched track, but Firebase already removes them.
            # Just to be extremely safe, we strip them.
            clean_track = {k: v for k, v in full_track.items() if v is not None}
            
            sync_group = self._generate_id()
            path_instreamz = f"/instreamz/familyz/{self.family_key}/trackz/{self.uid}/{sync_group}/value/{track_id}.json"
            self._do_request("PUT", f"{self.DB_URL}{path_instreamz}?auth={self.id_token}", json=clean_track)
            
        return track_id

    def log_activity(self, track_type, begin_dt=None, end_dt=None, track_id=None, **kwargs):
        """
        Low-level method to push any activity using the Firebase JSON schema.
        
        Args:
            track_type (str): The track type (e.g., "SLEEP", "FEED", "DIAPER").
            begin_dt (int, optional): Timestamp in milliseconds. Defaults to now.
            end_dt (int, optional): Timestamp in milliseconds for completion.
            track_id (str, optional): The ID of the track to edit.
            **kwargs: Additional fields to include in the Firebase payload.
            
        Returns:
            str: The track ID (key) of the logged activity.
        """
        if begin_dt is None:
            begin_dt = int(time.time() * 1000)
            
        payload = {
            "type": track_type,
            "beginDt": begin_dt,
            "ord": -begin_dt,
            "tz": self._get_local_timezone(),
            "createUserKey": self.uid,
            "userKey": self.uid,
            "updateDt": int(time.time() * 1000)
        }
        if end_dt:
            payload["endDt"] = end_dt
            
        payload.update(kwargs)
        track_id = self._push_payload(payload, track_id=track_id)
        print(f"Successfully logged {track_type} with ID: {track_id}")
        return track_id

    def log_note(self, text, begin_dt=None, **kwargs):
        """
        Log a standalone journal note for the child or pregnancy.
        
        Args:
            text (str): The content of the journal note.
            begin_dt (int, optional): Timestamp in milliseconds. Defaults to now.
            **kwargs: Additional fields (e.g., track_id for editing).
            
        Returns:
            str: The track ID of the logged note.
        """
        return self.log_activity("PARENT_NOTE", note=text, begin_dt=begin_dt, **kwargs)

    def log_breast_feed(self, side="LEFT", duration_minutes=0, begin_dt=None, **kwargs):
        """
        Log a manual breast feed session without using the timer.
        
        Args:
            side (str, optional): The side of the breast ("LEFT", "RIGHT", or "BOTH"). Defaults to "LEFT".
            duration_minutes (float, optional): The duration of the feed in minutes. Defaults to 0.
            begin_dt (int, optional): Timestamp in milliseconds. Defaults to now.
            **kwargs: Additional fields (e.g., note, track_id).
            
        Returns:
            str: The track ID of the logged feed.
        """
        VALID_SIDES = ["LEFT", "RIGHT", "BOTH"]
        if side.upper() not in VALID_SIDES:
            raise ValueError(f"Invalid side: '{side}'. Must be one of {VALID_SIDES}.")
        side = side.upper()
        
        duration_ms = int(duration_minutes * 60000)
        payload = {
            "feedType": "BREAST",
            "breastBeginSide": side,
            "breastEndSide": side,
        }
        
        if side == "LEFT":
            payload["breastLeftDuration"] = duration_ms
        elif side == "RIGHT":
            payload["breastRightDuration"] = duration_ms
        elif side == "BOTH":
            # If BOTH, just split the duration evenly. 
            payload["breastLeftDuration"] = int(duration_ms / 2)
            payload["breastRightDuration"] = int(duration_ms / 2)
            
        return self.log_activity("FEED", begin_dt=begin_dt, **payload, **kwargs)

    def start_breast_feed(self, side="LEFT"):
        """
        Starts a new stateful breast feed timer.
        Returns the track_id.
        """
        side = side.upper()
        now = int(time.time() * 1000)
        payload = {
            "feedType": "BREAST",
            "breastBeginSide": side,
            "breastEndSide": side,
            "breastLeftDuration": 0,
            "breastRightDuration": 0,
        }
        if side == "LEFT":
            payload["breastLeftBeginDt"] = now
        elif side == "RIGHT":
            payload["breastRightBeginDt"] = now
            
        return self.log_activity("FEED", begin_dt=now, **payload)

    def pause_breast_feed(self, track_id, side=None):
        """
        Pauses an active breast feed timer for a specific side.
        If no sides remain active after pausing, the feed is finalized (stopped).
        """
        track = self.get_track(track_id)
        if not track:
            return False
            
        now = int(time.time() * 1000)
        updates = {"updateDt": now}
        
        left_active = track.get("breastLeftBeginDt") is not None
        right_active = track.get("breastRightBeginDt") is not None
        
        if (side == "LEFT" or side is None) and left_active:
            elapsed = now - track["breastLeftBeginDt"]
            updates["breastLeftDuration"] = track.get("breastLeftDuration", 0) + elapsed
            updates["breastLeftBeginDt"] = None
            left_active = False
            
        if (side == "RIGHT" or side is None) and right_active:
            elapsed = now - track["breastRightBeginDt"]
            updates["breastRightDuration"] = track.get("breastRightDuration", 0) + elapsed
            updates["breastRightBeginDt"] = None
            right_active = False
            
        # If neither side is active anymore, finalize the feed entirely!
        if not left_active and not right_active:
            updates["endDt"] = now
            
        self.patch_activity(track_id, updates)
        return True

    def resume_breast_feed(self, track_id, side=None):
        """
        Resumes a paused breast feed timer, or switches sides dynamically.
        """
        track = self.get_track(track_id)
        if not track:
            return False
            
        now = int(time.time() * 1000)
        updates = {"updateDt": now}
        
        # If we are resuming a finalized track, we must remove endDt!
        if track.get("endDt"):
            updates["endDt"] = None
            
        # Determine the current active side if we are already running
        running_side = None
        if track.get("breastLeftBeginDt"):
            running_side = "LEFT"
        elif track.get("breastRightBeginDt"):
            running_side = "RIGHT"
            
        # If no side provided, just resume the last side we were on. If we don't know, default to LEFT.
        target_side = side.upper() if side else (running_side or track.get("breastEndSide", "LEFT"))
        
        # If we were actively running on a DIFFERENT side, we must pause it first to aggregate time
        if running_side and running_side != target_side:
            elapsed = now - track[f"breast{running_side.capitalize()}BeginDt"]
            updates[f"breast{running_side.capitalize()}Duration"] = track.get(f"breast{running_side.capitalize()}Duration", 0) + elapsed
            updates[f"breast{running_side.capitalize()}BeginDt"] = None
            
        updates[f"breast{target_side.capitalize()}BeginDt"] = now
        updates["breastEndSide"] = target_side
        
        self.patch_activity(track_id, updates)
        return True

    def stop_breast_feed(self, track_id):
        """
        Stops the active feed timer, finalizes durations, and removes the timer state.
        """
        track = self.get_track(track_id)
        if not track:
            return False
            
        now = int(time.time() * 1000)
        updates = {
            "endDt": now,
            "updateDt": now,
            "breastLeftBeginDt": None,
            "breastRightBeginDt": None
        }
        
        # Finalize left side
        if track.get("breastLeftBeginDt"):
            elapsed = now - track["breastLeftBeginDt"]
            updates["breastLeftDuration"] = track.get("breastLeftDuration", 0) + elapsed
            updates["breastEndSide"] = "LEFT"
            
        # Finalize right side
        if track.get("breastRightBeginDt"):
            elapsed = now - track["breastRightBeginDt"]
            updates["breastRightDuration"] = track.get("breastRightDuration", 0) + elapsed
            updates["breastEndSide"] = "RIGHT"
                
        self.patch_activity(track_id, updates)
        return True

    def start_sleep(self):
        """
        Starts an active, real-time sleep timer.
        Returns the track_id.
        """
        now = int(time.time() * 1000)
        payload = {
            "type": "SLEEP",
            "endDt": None
        }
        return self.log_activity("SLEEP", begin_dt=now, **payload)

    def stop_sleep(self, track_id):
        """
        Stops an active sleep timer.
        """
        now = int(time.time() * 1000)
        updates = {
            "endDt": now,
            "updateDt": now
        }
        self.patch_activity(track_id, updates)
        return True

    def start_pump(self, side="LEFT"):
        """
        Starts an active, real-time pump timer.
        Returns the track_id.
        """
        side = side.upper()
        now = int(time.time() * 1000)
        payload = {
            "type": "PUMP",
            "breastBoth": False,
            "endDt": now,
            "breastLeftDuration": 0,
            "breastRightDuration": 0,
        }
        if side == "LEFT":
            payload["breastLeftBeginDt"] = now
        elif side == "RIGHT":
            payload["breastRightBeginDt"] = now
            
        return self.log_activity("PUMP", begin_dt=now, **payload)

    def pause_pump(self, track_id, side=None):
        """
        Pauses an active pump timer for a specific side.
        If no sides remain active after pausing, the feed is finalized (stopped).
        """
        track = self.get_track(track_id)
        if not track:
            return False
            
        now = int(time.time() * 1000)
        updates = {"updateDt": now}
        
        left_active = track.get("pumpLeftBeginDt") is not None
        right_active = track.get("pumpRightBeginDt") is not None
        
        if (side == "LEFT" or side is None) and left_active:
            elapsed = now - track["pumpLeftBeginDt"]
            updates["pumpLeftDuration"] = track.get("pumpLeftDuration", 0) + elapsed
            updates["pumpLeftBeginDt"] = None
            left_active = False
            
        if (side == "RIGHT" or side is None) and right_active:
            elapsed = now - track["pumpRightBeginDt"]
            updates["pumpRightDuration"] = track.get("pumpRightDuration", 0) + elapsed
            updates["pumpRightBeginDt"] = None
            right_active = False
            
        # If neither side is active anymore, finalize the feed entirely!
        if not left_active and not right_active:
            updates["endDt"] = now
            
        self.patch_activity(track_id, updates)
        return True

    def resume_pump(self, track_id, side=None):
        """
        Resumes a paused pump timer, or switches sides dynamically.
        """
        track = self.get_track(track_id)
        if not track:
            return False
            
        now = int(time.time() * 1000)
        updates = {"updateDt": now}
        
        # If we are resuming a finalized track, we must remove endDt!
        if track.get("endDt"):
            updates["endDt"] = None
            
        # Determine the current active side if we are already running
        running_side = None
        if track.get("pumpLeftBeginDt"):
            running_side = "LEFT"
        elif track.get("pumpRightBeginDt"):
            running_side = "RIGHT"
            
        if running_side and running_side != side:
            # They want to switch sides! 
            if running_side == "LEFT":
                elapsed = now - track["pumpLeftBeginDt"]
                updates["pumpLeftDuration"] = track.get("pumpLeftDuration", 0) + elapsed
                updates["pumpLeftBeginDt"] = None
            else:
                elapsed = now - track["pumpRightBeginDt"]
                updates["pumpRightDuration"] = track.get("pumpRightDuration", 0) + elapsed
                updates["pumpRightBeginDt"] = None
        
        if side == "LEFT":
            updates["pumpLeftBeginDt"] = now
        elif side == "RIGHT":
            updates["pumpRightBeginDt"] = now
            
        self.patch_activity(track_id, updates)
        return True

    def stop_pump(self, track_id, left_vol_floz=0, right_vol_floz=0):
        """
        Stops the active pump timer and logs the final volume.
        """
        track = self.get_track(track_id)
        if not track:
            return False
            
        now = int(time.time() * 1000)
        updates = {
            "endDt": now,
            "updateDt": now,
            "breastLeftBeginDt": None,
            "breastRightBeginDt": None
        }
        
        if track.get("breastLeftBeginDt"):
            elapsed = now - track["breastLeftBeginDt"]
            updates["breastLeftDuration"] = track.get("breastLeftDuration", 0) + elapsed
            
        if track.get("breastRightBeginDt"):
            elapsed = now - track["breastRightBeginDt"]
            updates["breastRightDuration"] = track.get("breastRightDuration", 0) + elapsed
            
        if left_vol_floz > 0:
            updates["breastLeftVolumeNum"] = left_vol_floz
            updates["breastLeftVolumeBase"] = 1
            updates["breastLeftVolumeExp"] = 0
            updates["breastLeftVolumeUnit"] = "FLOZ"
            
        if right_vol_floz > 0:
            updates["breastRightVolumeNum"] = right_vol_floz
            updates["breastRightVolumeBase"] = 1
            updates["breastRightVolumeExp"] = 0
            updates["breastRightVolumeUnit"] = "FLOZ"
                
        self.patch_activity(track_id, updates)
        return True

    def log_bottle_feed(self, breast_milk=True, volume_floz=0, formula_name=None, begin_dt=None, **kwargs):
        """
        Log a bottle feed (breast milk or formula).
        
        Args:
            breast_milk (bool, optional): True if breast milk, False if formula. Defaults to True.
            volume_floz (float, optional): The volume fed in fluid ounces. Defaults to 0.
            formula_name (str, optional): The name of the formula if applicable.
            begin_dt (int, optional): Timestamp in milliseconds. Defaults to now.
            **kwargs: Additional fields (e.g., note, track_id).
            
        Returns:
            str: The track ID of the logged feed.
        """
        payload = {
            "feedType": "BOTTLE",
            "bottleTypeBreastMilk": breast_milk,
            "bottleTypeFormula": not breast_milk,
        }
        if volume_floz:
            vol_num = int(volume_floz * 100)
            payload.update({
                "bottleVolumeNum": vol_num, "bottleVolumeExp": 1, "bottleVolumeUnit": "FLOZ",
                "bottleVolume": vol_num, "bottleVolumeBase": vol_num
            })
            if breast_milk:
                payload.update({"bottleBreastMilkVolumeNum": vol_num, "bottleBreastMilkVolumeExp": 1, "bottleBreastMilkVolumeUnit": "FLOZ"})
            else:
                payload.update({"bottleFormulaVolumeNum": vol_num, "bottleFormulaVolumeExp": 1, "bottleFormulaVolumeUnit": "FLOZ"})
        
        if formula_name and not breast_milk:
            payload["formulaName"] = formula_name
            
        return self.log_activity("FEED", begin_dt=begin_dt, **payload, **kwargs)

    def log_solid_feed(self, begin_dt=None, **kwargs):
        """
        Log a solid food feed.
        
        Args:
            begin_dt (int, optional): Timestamp in milliseconds. Defaults to now.
            **kwargs: Additional fields (e.g., note for describing the food, track_id).
            
        Returns:
            str: The track ID of the logged feed.
        """
        return self.log_activity("FEED", feedType="SOLID", begin_dt=begin_dt, **kwargs)

    def log_combo_feed(self, breast_side="LEFT", breast_duration_ms=0, volume_floz=0, breast_milk=True, formula_name=None, begin_dt=None, **kwargs):
        """
        Log a combo feed (breast + bottle).
        
        Args:
            breast_side (str, optional): The side of the breast ("LEFT", "RIGHT", or "BOTH"). Defaults to "LEFT".
            breast_duration_ms (int, optional): Duration on the breast in milliseconds. Defaults to 0.
            volume_floz (float, optional): The volume fed via bottle in fluid ounces. Defaults to 0.
            breast_milk (bool, optional): True if the bottle was breast milk, False if formula. Defaults to True.
            formula_name (str, optional): The name of the formula if applicable.
            begin_dt (int, optional): Timestamp in milliseconds. Defaults to now.
            **kwargs: Additional fields (e.g., note, track_id).
            
        Returns:
            str: The track ID of the logged combo feed.
        """
        VALID_SIDES = ["LEFT", "RIGHT", "BOTH"]
        if breast_side.upper() not in VALID_SIDES:
            raise ValueError(f"Invalid breast_side: '{breast_side}'. Must be one of {VALID_SIDES}.")
        breast_side = breast_side.upper()
        
        payload = {
            "feedType": "COMBO",
            "breastBeginSide": breast_side,
            "breastEndSide": breast_side,
            "bottleTypeBreastMilk": breast_milk,
            "bottleTypeFormula": not breast_milk,
        }
        
        if breast_side == "LEFT":
            payload["breastLeftDuration"] = breast_duration_ms
        elif breast_side == "RIGHT":
            payload["breastRightDuration"] = breast_duration_ms
        elif breast_side == "BOTH":
            payload["breastLeftDuration"] = int(breast_duration_ms / 2)
            payload["breastRightDuration"] = int(breast_duration_ms / 2)
            
        if volume_floz:
            vol_num = int(volume_floz * 100)
            payload.update({
                "bottleVolumeNum": vol_num, "bottleVolumeExp": 1, "bottleVolumeUnit": "FLOZ",
                "bottleVolume": vol_num, "bottleVolumeBase": vol_num
            })
            if breast_milk:
                payload.update({"bottleBreastMilkVolumeNum": vol_num, "bottleBreastMilkVolumeExp": 1, "bottleBreastMilkVolumeUnit": "FLOZ"})
            else:
                payload.update({"bottleFormulaVolumeNum": vol_num, "bottleFormulaVolumeExp": 1, "bottleFormulaVolumeUnit": "FLOZ"})
        
        if formula_name and not breast_milk:
            payload["formulaName"] = formula_name
            
        return self.log_activity("FEED", begin_dt=begin_dt, **payload, **kwargs)

    def log_milestone(self, milestone_name, begin_dt=None, **kwargs):
        """
        Log a developmental milestone.
        
        Args:
            milestone_name (str): The name or description of the milestone (e.g. "First Steps").
            begin_dt (int, optional): Timestamp in milliseconds. Defaults to now.
            **kwargs: Additional fields (e.g., note, track_id).
            
        Returns:
            str: The track ID of the logged milestone.
        """
        return self.log_activity("GROW.MILESTONE", milestoneName=milestone_name, begin_dt=begin_dt, **kwargs)
        
    def log_medical_appointment(self, doctor_name=None, begin_dt=None, **kwargs):
        """
        Log a medical appointment.
        
        Args:
            doctor_name (str, optional): The name of the doctor or clinic.
            begin_dt (int, optional): Timestamp in milliseconds. Defaults to now.
            **kwargs: Additional fields (e.g., note, track_id).
            
        Returns:
            str: The track ID of the logged appointment.
        """
        payload = {}
        if doctor_name:
            payload["doctorName"] = doctor_name
        return self.log_activity("MEDICAL.APPOINTMENT", begin_dt=begin_dt, **payload, **kwargs)
        
    def log_vaccine(self, vaccine_name, begin_dt=None, **kwargs):
        """
        Log a medical vaccine.
        
        Args:
            vaccine_name (str): The name of the vaccine.
            begin_dt (int, optional): Timestamp in milliseconds. Defaults to now.
            **kwargs: Additional fields (e.g., note, track_id).
            
        Returns:
            str: The track ID of the logged vaccine.
        """
        return self.log_activity("MEDICAL.VACCINE", vaccineName=vaccine_name, begin_dt=begin_dt, **kwargs)

    # --- SPECIFIC ACTIVITY HELPERS ---

    def log_diaper(self, pee=True, poop=False, dry=False, rash=False, blowout=False, color=None, texture=None, begin_dt=None, **kwargs):
        """
        Log a diaper change.
        
        Args:
            pee (bool, optional): True if the diaper was wet. Defaults to True.
            poop (bool, optional): True if the diaper was soiled. Defaults to False.
            dry (bool, optional): True if the diaper was dry. Defaults to False.
            rash (bool, optional): True if a diaper rash was observed. Defaults to False.
            blowout (bool, optional): True if there was a poop blowout. Defaults to False.
            color (str, optional): The color of the poop ("BLACK", "BROWN", "GRAY", "GREEN", "RED", "YELLOW").
            texture (str, optional): The texture of the poop ("MUSHY", "SEEDY", "RUNNY", "HARD", "SOLID").
            begin_dt (int, optional): Timestamp in milliseconds. Defaults to now.
            **kwargs: Additional fields (e.g., note, track_id).
            
        Returns:
            str: The track ID of the logged diaper change.
        """
        VALID_COLORS = ["BLACK", "BROWN", "GRAY", "GREEN", "RED", "YELLOW"]
        VALID_TEXTURES = ["MUCOUS", "MUSH", "PEBBLE", "RUN", "SOLID"]
        
        if color and color.upper() not in VALID_COLORS:
            raise ValueError(f"Invalid color: '{color}'. Must be one of {VALID_COLORS}.")
        if texture and texture.upper() not in VALID_TEXTURES:
            raise ValueError(f"Invalid texture: '{texture}'. Must be one of {VALID_TEXTURES}.")
            
        payload = {
            "track_type": "DIAPER",
            "diaperTypePee": pee,
            "diaperTypePoop": poop,
            "diaperTypeDry": dry,
            "diaperTypeRash": rash,
        }
        if poop:
            payload["diaperPoopBlowout"] = blowout
            if color:
                payload["diaperPoopColor"] = color.upper()
            if texture:
                payload["diaperPoopTexture"] = texture.upper()
                
        return self.log_activity(
            begin_dt=begin_dt,
            **payload,
            **kwargs
        )

    def log_sleep(self, begin_dt, end_dt, **kwargs):
        """
        Log a complete sleep session.
        
        Args:
            begin_dt (int): Start timestamp in milliseconds.
            end_dt (int): End timestamp in milliseconds.
            **kwargs: Additional fields (e.g., note, track_id).
            
        Returns:
            str: The track ID of the logged sleep session.
        """
        return self.log_activity(
            track_type="SLEEP",
            begin_dt=begin_dt,
            end_dt=end_dt,
            **kwargs
        )

    def log_routine(self, routine_name, begin_dt=None, **kwargs):
        """
        Log a routine like 'Bath', 'Nail trim', or 'Tummy time'.
        
        Args:
            routine_name (str): The name of the routine.
            begin_dt (int, optional): Timestamp in milliseconds. Defaults to now.
            **kwargs: Additional fields (e.g., note, track_id).
            
        Returns:
            str: The track ID of the logged routine.
        """
        VALID_ROUTINES = ["BATH", "NAILTRIM", "OUTDOOR", "PLAY", "READ", "TUMMYTIME", "VITAMIN"]
        if routine_name.upper() not in VALID_ROUTINES:
            raise ValueError(f"Invalid routine_name: '{routine_name}'. Must be one of {VALID_ROUTINES}.")
            
        return self.log_activity(
            track_type="ROUTINE",
            routineName=routine_name.upper(),
            begin_dt=begin_dt,
            **kwargs
        )

    def log_growth(self, weight_lb=None, height_in=None, head_in=None, begin_dt=None):
        """
        Log growth measurements.
        
        Args:
            weight_lb (float, optional): Weight in pounds.
            height_in (float, optional): Height/length in inches.
            head_in (float, optional): Head circumference in inches.
            begin_dt (int, optional): Timestamp in milliseconds. Defaults to now.
            
        Returns:
            str: The track ID of the logged growth entry.
        """
        payload = {}
        if weight_lb:
            payload.update({"weightNum": int(weight_lb * 1000), "weightExp": 4, "weightUnit": "LB"})
        if height_in:
            payload.update({"heightNum": int(height_in * 10), "heightExp": 1, "heightUnit": "IN"})
        if head_in:
            payload.update({"headSizeNum": int(head_in * 10), "headSizeExp": 1, "headSizeUnit": "IN"})
            
        return self.log_activity("GROW", begin_dt=begin_dt, **payload)
        
    def log_health(self, medicine_name=None, temp_f=None, begin_dt=None):
        """
        Log health and medicine information.
        
        Args:
            medicine_name (str, optional): Name of the medicine given (e.g., "Tylenol").
            temp_f (float, optional): Temperature reading in Fahrenheit.
            begin_dt (int, optional): Timestamp in milliseconds. Defaults to now.
            
        Returns:
            str: The track ID of the logged health entry.
        """
        payload = {}
        type_str = "MEDICAL.MEDICINE"
        if medicine_name:
            payload["medicineName"] = medicine_name
            payload["medicinez"] = [{"key": medicine_name}]
        if temp_f:
            payload.update({"temperatureNum": int(temp_f * 10), "temperatureExp": 1, "temperatureUnit": "F"})
            type_str = "MEDICAL.TEMPERATURE"
            
        return self.log_activity(type_str, begin_dt=begin_dt, **payload)

    def log_pump(self, begin_dt, end_dt, left_vol_floz=None, right_vol_floz=None, **kwargs):
        """
        Log a breast pump session.
        
        Args:
            begin_dt (int): Start timestamp in milliseconds.
            end_dt (int): End timestamp in milliseconds.
            left_vol_floz (float, optional): Volume pumped from left breast in fluid ounces.
            right_vol_floz (float, optional): Volume pumped from right breast in fluid ounces.
            **kwargs: Additional fields (e.g., note, track_id).
            
        Returns:
            str: The track ID of the logged pump session.
        """
        payload = {"breastBoth": False}
        if left_vol_floz:
            payload.update({"breastLeftVolumeNum": int(left_vol_floz * 100), "breastLeftVolumeExp": 1, "breastLeftVolumeUnit": "FLOZ"})
        if right_vol_floz:
            payload.update({"breastRightVolumeNum": int(right_vol_floz * 100), "breastRightVolumeExp": 1, "breastRightVolumeUnit": "FLOZ"})
            
        return self.log_activity(
            track_type="PUMP",
            begin_dt=begin_dt,
            end_dt=end_dt,
            **payload,
            **kwargs
        )

    # --- TIMER MANAGEMENT ---

    # Obsolete local timers removed to favor stateful Firebase real-time timers.
