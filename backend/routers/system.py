import os
import threading
import time

from fastapi import APIRouter

router = APIRouter(tags=["system"])


# Shutdown route for the PC app to close the server
@router.post("/shutdown")
def shutdown():
    def stop():
        time.sleep(0.5)
        os._exit(0)

    threading.Thread(target=stop).start()
    return {"message": "Server shutting down"}
