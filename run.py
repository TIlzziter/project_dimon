import sys

from app import create_app
from app.config import load_settings
from app.db import connect
from app.domain import seed_demo


def main() -> None:
    settings = load_settings()
    if len(sys.argv) > 1 and sys.argv[1] == "seed-demo":
        app = create_app(settings)
        connection = connect(settings.db_path)
        created = seed_demo(connection)
        connection.commit()
        connection.close()
        if created:
            print("Добавлены: " + ", ".join(created))
        else:
            print("Демо-пользователи уже есть")
        print("duty1 / duty1, duty2 / duty2, brig / brig, admin / admin")
        return
    app = create_app(settings)
    print(f"Журнал: http://{settings.host}:{settings.port}")
    app.run(host=settings.host, port=settings.port, debug=False)


if __name__ == "__main__":
    main()
