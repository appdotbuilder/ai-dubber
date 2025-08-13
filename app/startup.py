from app.database import create_tables
import app.video_dubbing


def startup() -> None:
    # this function is called before the first request
    create_tables()

    # Initialize video dubbing module
    app.video_dubbing.create()
