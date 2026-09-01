import os
import threading
import time

from fastapi import FastAPI

app = FastAPI(title="Opsy API")


@app.get("/")
def root():
    return {"message": "success"}


@app.get("/health")
def health():
    return {"status": "ok"}


# Shutdown route for the PC app to close the server
@app.post("/shutdown")
def shutdown():
    def stop():
        time.sleep(0.5)
        os._exit(0)

    threading.Thread(target=stop).start()
    return {"message": "Server shutting down"}
