import uvicorn
import logging
import sys

logging.basicConfig(level=logging.DEBUG)

if __name__ == "__main__":
    uvicorn.run("backend.main:app", host="127.0.0.1", port=8000, log_level="debug")
