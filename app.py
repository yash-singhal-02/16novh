import os

from flask import Flask, jsonify, request
from postgrest import APIError
from supabase import Client, create_client
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

supabase: Client = create_client(
    os.environ.get("SUPABASE_URL"),
    os.environ.get("SUPABASE_PUBLISHABLE_KEY"),
)


def api_error(message, status):
    return jsonify({"error": message}), status


def authenticated_user():
    """Return the Supabase user for the request's bearer token, or None."""
    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None

    try:
        response = supabase.auth.get_user(token.strip())
        return response.user
    except Exception:
        return None


def require_user():
    user = authenticated_user()
    if user is None:
        return None, api_error("Authentication required", 401)
    return user, None


@app.get("/")
def index():
    return jsonify({"message": "Events API"})


@app.get("/api/events")
def list_events():
    try:
        events = supabase.table("events").select("*").execute()
        return jsonify(events.data)
    except APIError as error:
        return api_error(error.message, 500)


@app.get("/api/events/<event_id>")
def get_event(event_id):
    try:
        response = (
            supabase.table("events")
            .select("*")
            .eq("id", event_id)
            .maybe_single()
            .execute()
        )
        if response.data is None:
            return api_error("Event not found", 404)
        return jsonify(response.data)
    except APIError as error:
        return api_error(error.message, 500)


@app.post("/api/registrations")
def create_registration():
    user, error_response = require_user()
    if error_response:
        return error_response

    body = request.get_json(silent=True) or {}
    event_id = body.get("event_id")
    if not event_id:
        return api_error("event_id is required", 400)

    try:
        existing = (
            supabase.table("registrations")
            .select("id")
            .eq("event_id", event_id)
            .eq("user_id", user.id)
            .maybe_single()
            .execute()
        )
        if existing.data:
            return api_error("Already registered for this event", 409)

        created = (
            supabase.table("registrations")
            .insert({"event_id": event_id, "user_id": user.id})
            .execute()
        )
        return jsonify(created.data[0] if created.data else {}), 201
    except APIError as error:
        # A unique constraint on (event_id, user_id) also protects against
        # simultaneous duplicate requests.
        if getattr(error, "code", None) == "23505":
            return api_error("Already registered for this event", 409)
        if getattr(error, "code", None) == "23503":
            return api_error("Event not found", 404)
        return api_error(error.message, 500)


@app.get("/api/me/registrations")
def my_registrations():
    user, error_response = require_user()
    if error_response:
        return error_response

    try:
        registrations = (
            supabase.table("registrations")
            .select("*, events(*)")
            .eq("user_id", user.id)
            .execute()
        )
        return jsonify(registrations.data)
    except APIError as error:
        return api_error(error.message, 500)


@app.get("/api/events/<event_id>/registrations")
def event_registrations(event_id):
    user, error_response = require_user()
    if error_response:
        return error_response

    try:
        event = (
            supabase.table("events")
            .select("id, organizer_id")
            .eq("id", event_id)
            .maybe_single()
            .execute()
        )
        if event.data is None:
            return api_error("Event not found", 404)
        if str(event.data.get("organizer_id")) != str(user.id):
            return api_error("Only the event organizer can view registrations", 403)

        registrations = (
            supabase.table("registrations")
            .select("*")
            .eq("event_id", event_id)
            .execute()
        )
        return jsonify(registrations.data)
    except APIError as error:
        return api_error(error.message, 500)


if __name__ == "__main__":
    app.run(debug=True)
