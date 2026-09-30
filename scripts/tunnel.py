import logging
import os

from dotenv import dotenv_values

from bot.config import ROOT


def main():
    from pyngrok import conf, ngrok

    values = dotenv_values(ROOT / ".env", interpolate=False)
    if not values.get("NGROK_AUTHTOKEN") or not values.get("PORT"):
        raise SystemExit("Configura NGROK_AUTHTOKEN y PORT en .env.")
    logging.getLogger("pyngrok").setLevel(logging.CRITICAL)
    os.environ["NGROK_AUTHTOKEN"] = values["NGROK_AUTHTOKEN"]
    config = conf.PyngrokConfig()
    config.auth_token = None
    try:
        tunnel = ngrok.connect(
            addr=f"127.0.0.1:{int(values['PORT'])}",
            proto="http",
            bind_tls=True,
            inspect=False,
            pyngrok_config=config,
        )
        print("Callback para Meta:", tunnel.public_url + "/webhook")
        input("El túnel está activo. Enter lo cierra.\n")
    except Exception:
        raise SystemExit(
            "No se pudo abrir el túnel. Revisa tu cuenta y configuración de ngrok."
        ) from None
    finally:
        ngrok.kill(pyngrok_config=config)


if __name__ == "__main__":
    main()
