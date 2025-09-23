from locust import HttpUser, task, between
import json
import random
import time

class GameDBUser(HttpUser):
    wait_time = between(28, 32)  # Wait 28-32 seconds between task cycles (average 30s)
    
    def on_start(self):
        """Set up headers for compression testing"""
        self.client.headers.update({
            "Accept-Encoding": "gzip",
            "Content-Type": "application/json"
        })
    
    @task
    def user_session(self):
        """Each user performs one GET and one POST every ~30 seconds"""
        # GET request
        self.client.get("/get-objects")
        
        # Brief pause between requests (1-3 seconds)
        time.sleep(random.uniform(1, 3))
        
        # POST request
        test_data = {
            "o_type": random.randint(1, 100),
            "o_pos": f"{random.uniform(-100, 100):.2f},{random.uniform(-100, 100):.2f},{random.uniform(-100, 100):.2f}",
            "o_rot": f"{random.uniform(0, 360):.2f},{random.uniform(0, 360):.2f},{random.uniform(0, 360):.2f}"
        }
        self.client.post("/add-object", json=test_data)