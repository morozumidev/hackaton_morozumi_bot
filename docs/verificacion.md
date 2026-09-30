# Verificación

Se ejecutaron 43 pruebas automatizadas con Python 3.12; todas pasaron. También pasó la revisión de Ruff y el escaneo de archivos públicos.

Se verificó:

- Firma del webhook, rechazo de cuerpos alterados, eventos repetidos y mensajes antiguos.
- Límite de tamaño y frecuencia; manejo de mensajes que no son texto.
- Consulta de horarios mediante function calling y memoria entre turnos.
- Confirmación explícita, vencimiento de propuestas y persistencia al reiniciar.
- Dos usuarios intentando reservar el mismo horario: solo uno consigue la cita.
- Consulta y cancelación limitadas al dueño de la cita.
- Bloqueo ante fallos de las guardas o respuestas inseguras.
- Reintentos de envío que reutilizan la respuesta sin repetir la reserva.
- Eliminación del destinatario y el cuerpo de los trabajos terminados.

Las llamadas a Meta, Llama, Llama Guard y Prompt Guard se simulan en las pruebas. No se ejecutó una conversación real en WhatsApp ni inferencia con los modelos: faltan las credenciales locales de Meta y tener Ollama con los modelos activos. Prompt Guard requiere además configurar una API key de Groq.

Para reproducir las comprobaciones, con las dependencias instaladas:

```bash
pytest -q
ruff check .
ruff format --check .
python -m scripts.check_public
```

El escáner revisa el árbol de trabajo y el índice de Git. No comprueba todo el historial ni garantiza detectar cualquier formato de secreto. `.env`, las bases SQLite y el entorno virtual están excluidos de Git. La plantilla pública tiene los campos privados vacíos.

La cola y la agenda están pensadas para una sola instancia. Un fallo de red después de que Meta acepte una respuesta puede duplicar el mensaje saliente al reintentar; la reserva permanece única. El borrado de datos es lógico; esta aplicación no cifra SQLite ni sus respaldos.
