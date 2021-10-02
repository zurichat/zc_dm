import json
import uuid
import re
from django.http import response
from django.utils.decorators import method_decorator
from django.http.response import JsonResponse
from django.shortcuts import render

from rest_framework import generics

from rest_framework.response import Response
from rest_framework.decorators import api_view, parser_classes
from rest_framework import status
import requests
import time
from .utils import send_centrifugo_data
from .db import *
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.views import APIView, exception_handler
from django.core.files.storage import default_storage

# Import Read Write function to Zuri Core
from .resmodels import *
from .serializers import *
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from datetime import datetime
import datetime as datetimemodule
from .centrifugo_handler import centrifugo_client
from rest_framework.pagination import PageNumberPagination
from .decorators import db_init_with_credentials
from rest_framework_simplejwt.tokens import RefreshToken
from queue import LifoQueue



def index(request):
    context = {}
    return render(request, "index.html", context)


# Shows basic information about the DM plugin
def info(request):
    info = {
        "message": "Plugin Information Retrieved",
        "data": {
            "type": "Plugin Information",
            "plugin_info": {
                "name": "DM Plugin",
                "description": [
                    "Zuri.chat plugin",
                    "DM plugin for Zuri Chat that enables users to send messages to each other",
                ],
            },
            "scaffold_structure": "Monolith",
            "team": "HNG 8.0/Team Orpheus",
            "sidebar_url": "https://dm.zuri.chat/api/v1/sidebar",
            "homepage_url": "https://dm.zuri.chat/dm",
            "create_room_url": "https://dm.zuri.chat/api/v1/<str:org_id>/room",
        },
        "success": "true",
    }

    return JsonResponse(info, safe=False)


def verify_user(token):
    """
    Call Endpoint for verification of user (sender)
    It takes in either token or cookies and returns a python dictionary of
    user info if 200 successful or 401 unathorized if not
    """
    url = "https://api.zuri.chat/auth/verify-token"

    headers = {}
    if "." in token:
        headers["Authorization"] = f"Bearer {token}"
    else:
        headers["Cookie"] = token

    response = requests.get(url, headers=headers)
    response = response.json()

    return response


# Returns the json data of the sidebar that will be consumed by the api
# The sidebar info will be unique for each logged in user
# user_id will be gotten from the logged in user
# All data in the message_rooms will be automatically generated from zuri core


def side_bar(request):
    org_id = request.GET.get("org", None)
    user = request.GET.get("user", None)
    user_rooms = get_rooms(user_id=user, org_id=org_id)
    rooms = []

    if user_rooms == None:
        pass
    else:
        for room in user_rooms:
            if "org_id" in room:
                if org_id == room["org_id"]:
                    room_profile = {}
                    for user_id in room["room_user_ids"]:
                        if user_id != user:
                            profile = get_user_profile(org_id, user_id)
                            if profile["status"] == 200:
                                room_profile["room_name"] = profile["data"]["user_name"]
                                if profile["data"]["image_url"]:
                                    room_profile["room_image"] = profile["data"][
                                        "image_url"
                                    ]
                                else:
                                    room_profile[
                                        "room_image"
                                    ] = "https://cdn.iconscout.com/icon/free/png-256/account-avatar-profile-human-man-user-30448.png"
                                rooms.append(room_profile)
                    room_profile["room_url"] = f"/dm/{org_id}/{room['_id']}/{user}"
    side_bar = {
        "name": "DM Plugin",
        "description": "Sends messages between users",
        "plugin_id": "6135f65de2358b02686503a7",
        "organisation_id": f"{org_id}",
        "user_id": f"{user}",
        "group_name": "DM",
        "show_group": False,
        "button_url": f"/dm/{org_id}/{user}/all-dms",
        "public_rooms": [],
        "joined_rooms": rooms,
        # List of rooms/collections created whenever a user starts a DM chat with another user
        # This is what will be displayed by Zuri Main
    }
    return JsonResponse(side_bar, safe=False)


@swagger_auto_schema(
    methods=["post", "get"],
    query_serializer=GetMessageSerializer,
    operation_summary="Creates and get messages",

    responses={
        201: MessageResponse,
        400: "Error: Bad Request"
    }

    responses={201: MessageResponse, 400: "Error: Bad Request"},

)
@api_view(["GET", "POST"])
@db_init_with_credentials
def message_create_get(request, room_id):
    if request.method == "GET":
        paginator = PageNumberPagination()
        paginator.page_size = 20
        date = request.GET.get("date", None)
        params_serializer = GetMessageSerializer(data=request.GET.dict())
        if params_serializer.is_valid():
            room = DB.read("dm_rooms", {"_id": room_id})
            if room:
                messages = get_room_messages(room_id, DB.organization_id)
                if date != None:
                    messages_by_date = get_messages(messages, date)
                    if messages_by_date == None or "message" in messages_by_date:
                        return Response(
                            data="No messages available",
                            status=status.HTTP_204_NO_CONTENT,
                        )
                    else:
                        messages_page = paginator.paginate_queryset(
                            messages_by_date, request
                        )
                        return paginator.get_paginated_response(messages_page)
                else:
                    if messages == None or "message" in messages:
                        return Response(
                            data="No messages available",
                            status=status.HTTP_204_NO_CONTENT,
                        )
                    result_page = paginator.paginate_queryset(
                        messages, request)
                    return paginator.get_paginated_response(result_page)
            else:
                return Response(data="No such room", status=status.HTTP_404_NOT_FOUND)
        else:
            return Response(
                params_serializer.errors, status=status.HTTP_400_BAD_REQUEST
            )

    elif request.method == "POST":
        request.data["room_id"] = room_id
        print(request)
        serializer = MessageSerializer(data=request.data)

        if serializer.is_valid():
            data = serializer.data
            room_id = data["room_id"]  # room id gotten from client request

            room = DB.read("dm_rooms", {"_id": room_id})
            if room and room.get('status_code', None) == None:
                if data["sender_id"] in room.get("room_user_ids", []):

                    response = DB.write("dm_messages", data=serializer.data)
                    if response.get("status", None) == 200:

                        response_output = {
                            "status": response["message"],
                            "event": "message_create",
                            "message_id": response["data"]["object_id"],
                            "room_id": room_id,
                            "thread": False,
                            "data": {
                                "sender_id": data["sender_id"],
                                "message": data["message"],
                                "created_at": data["created_at"],
                            }
                        }
                        try:
                            centrifugo_data = centrifugo_client.publish(
                                room=room_id, data=response_output)  # publish data to centrifugo
                            if centrifugo_data and centrifugo_data.get("status_code") == 200:
                                return Response(data=response_output, status=status.HTTP_201_CREATED)
                            else:
                                return Response(data="message not sent", status=status.HTTP_424_FAILED_DEPENDENCY)
                        except:
                            return Response(data="centrifugo server not available", status=status.HTTP_424_FAILED_DEPENDENCY)
                    return Response(data="message not saved and not sent", status=status.HTTP_424_FAILED_DEPENDENCY)
                return Response("sender not in room", status=status.HTTP_400_BAD_REQUEST)
            return Response("room not found", status=status.HTTP_400_BAD_REQUEST)
        return Response(status=status.HTTP_400_BAD_REQUEST)


@swagger_auto_schema(
    methods=["post"],
    request_body=RoomSerializer,
    operation_summary="Creates a new room between users",
    responses={
        201: CreateRoomResponse,
        400: "Error: Bad Request"
    }
)
@api_view(["POST"])
@db_init_with_credentials
def create_room(request, member_id):
    """
    Creates a room between users.
    It takes the id of the users involved, sends a write request to the database .
    Then returns the room id when a room is successfully created
    """
    serializer = RoomSerializer(data=request.data)
    if serializer.is_valid():
        user_ids = serializer.data["room_member_ids"]

        if len(user_ids) > 2:
            # print("            --------MUKHTAR-------              \n\r")
            response = group_room(request, member_id)

            if response.get('get_group_data'):
                return Response(data=response['room_id'], status=response['status_code'])

            if response.get("get_group_data"):
                return Response(
                    data=response["room_id"], status=response["status_code"]
                )


        else:
            # print("            --------FAE-------              \n\r")
            user_ids = serializer.data["room_member_ids"]
            user_rooms = get_rooms(user_ids[0], DB.organization_id)
            if "status_code" in user_rooms:
                pass
            else:
                for room in user_rooms:
                    room_users = room["room_user_ids"]
                    if set(room_users) == set(user_ids):

                        response_output = {
                            "room_id": room["_id"]
                        }
                        return Response(data=response_output, status=status.HTTP_200_OK)

            fields = {"org_id": serializer.data["org_id"],
                      "room_user_ids": serializer.data["room_member_ids"],
                      "room_name": serializer.data["room_name"],
                      "private": serializer.data["private"],
                      "created_at": serializer.data["created_at"],
                      "bookmark": [],
                      "pinned": [],
                      "starred": []
                      }

                        response_output = {"room_id": room["_id"]}
                        return Response(data=response_output, status=status.HTTP_200_OK)

            fields = {
                "org_id": serializer.data["org_id"],
                "room_user_ids": serializer.data["room_member_ids"],
                "room_name": serializer.data["room_name"],
                "private": serializer.data["private"],
                "created_at": serializer.data["created_at"],
                "bookmark": [],
                "pinned": [],
                "starred": [],
            }


            response = DB.write("dm_rooms", data=fields)
            # ===============================

        data = response.get("data").get("object_id")
        if response.get("status") == 200:
            response_output = {
                "event": "sidebar_update",
                "plugin_id": "dm.zuri.chat",
                "data": {
                    "group_name": "DM",
                    "name": "DM Plugin",
                    "show_group": False,
                    "button_url": "/dm",
                    "public_rooms": [],

                    # added extra param
                    "joined_rooms": sidebar_emitter(org_id=DB.organization_id, member_id=member_id, group_room_name=serializer.data["room_name"])
                }

                    "joined_rooms": sidebar_emitter(
                        org_id=DB.organization_id,
                        member_id=member_id,
                        group_room_name=serializer.data["room_name"],
                    ),  # added extra param
                },

            }

            try:
                centrifugo_data = centrifugo_client.publish(

                    room=f"{DB.organization_id}_{member_id}_sidebar", data=response_output)  # publish data to centrifugo
                if centrifugo_data and centrifugo_data.get("status_code") == 200:
                    return Response(data=response_output, status=status.HTTP_201_CREATED)

                    room=f"{DB.organization_id}_{member_id}_sidebar",
                    data=response_output,
                )  # publish data to centrifugo
                if centrifugo_data and centrifugo_data.get("status_code") == 200:
                    return Response(
                        data=response_output, status=status.HTTP_201_CREATED
                    )

                else:
                    return Response(
                        data="room created but centrifugo failed",
                        status=status.HTTP_424_FAILED_DEPENDENCY,
                    )
            except:
                return Response(
                    data="centrifugo server not available",
                    status=status.HTTP_424_FAILED_DEPENDENCY,
                )
        return Response("data not sent", status=status.HTTP_424_FAILED_DEPENDENCY)
    return Response(data="Invalid data", status=status.HTTP_400_BAD_REQUEST)


@swagger_auto_schema(
    methods=["get"],
    operation_summary="Retrieves all rooms linked to a user id",
    query_serializer=UserRoomsSerializer,
    responses={
        200: "OK: Success",
        204: "No Rooms Available",
        400: "Error: Bad Request",
    },
)
@api_view(["GET"])
@db_init_with_credentials
def user_rooms(request, user_id):
    """
    Retrieves all rooms a user is currently active in.
    if there is no room for the user_id it returns a 204 status response.
    """
    if request.method == "GET":
        res = get_rooms(user_id, DB.organization_id)
        if res == None:
            return Response(
                data="No rooms available", status=status.HTTP_204_NO_CONTENT
            )
        return Response(res, status=status.HTTP_200_OK)
    return Response(status=status.HTTP_400_BAD_REQUEST)


@swagger_auto_schema(
    methods=["get"],
    operation_summary="Retrieves all the information about a room",
    query_serializer=RoomInfoSerializer,
    responses={
        200: RoomInfoResponse,
        400: "Error: Bad Request",
        404: "Error: Room Not Found",
    }
)
@api_view(["GET"])
@db_init_with_credentials
def room_info(request, room_id):
    """
    Retrieves information about a room.
    It takes the room id and searches the dm_rooms collection
    If the room exists, a json response of the room details is returned
    Else a 404 response is returned with a "No such room" message
    """
    # room_id = request.GET.get("room_id", None)
    org_id = DB.organization_id
    room_collection = "dm_rooms"
    current_room = DB.read(room_collection, {"_id": room_id})
    print(current_room)
    if current_room and current_room.get("status_code", None) == None:

        if "room_user_ids" in current_room:
            room_user_ids = current_room["room_user_ids"]
        elif "room_member_ids" in current_room:
            room_user_ids = current_room["room_member_ids"] 
        else:
            room_user_ids = ""
        if "starred" in current_room:
            starred = current_room["starred"]
        else:
            starred = ""
        if "pinned" in current_room:
            pinned = current_room["pinned"]
        else:
            pinned = ""
        if "bookmark" in current_room:
            bookmark = current_room["bookmark"]
        else:
            bookmark = ""
        if "private" in current_room:
            private = current_room["private"]
        else:
            private = ""
        if "created_at" in current_room:
            created_at = current_room["created_at"]
        else:
            created_at = ""
        if "org_id" in current_room:
            org_id = current_room["org_id"]

        if len(room_user_ids) > 3:
            text = f" and {len(room_user_ids)-2} others"
        elif len(room_user_ids) == 3:
            text = " and 1 other"
        else:
            text = " only"
        if  len(room_user_ids) >= 1:
            user1 = get_user_profile(org_id=org_id, user_id=room_user_ids[0])
            if user1["status"] == 200:
                user_name_1 = user1["data"]["user_name"]
            else:
                user_name_1 = room_user_ids[0]
        else: 
            user_name_1 = "Some user"
        if len(room_user_ids) > 1:
            user2 = get_user_profile(org_id=org_id, user_id=room_user_ids[1])
            if user2["status"] == 200:
                user_name_2 = user2["data"]["user_name"]
            else:
                user_name_2 = room_user_ids[1]
        else:
            user_name_2 = "Some user"
        room_data = {
            "room_id": room_id,
            "org_id": org_id,
            "room_user_ids": room_user_ids,
            "created_at": created_at,
            "description": f"This room contains the coversation between {user_name_1} and {user_name_2}{text}",
            "starred": starred,
            "pinned": pinned,
            "private": private,
            "bookmarks": bookmark,
            "Number of users": f"{len(room_user_ids)}",

        }
        return Response(data=room_data, status=status.HTTP_200_OK)
    return Response(data="Room not found", status=status.HTTP_404_NOT_FOUND)


# /code for updating room
@api_view(["GET", "PUT"])
@db_init_with_credentials
def edit_message(request, message_id, room_id):
    """
    This is used to update message context using message id as identifier,
    first --> we check if this message exist, if it does not exist we raise message doesnot exist,
    if above message exists:
        pass GET request to view the message one whats to edit.
        or pass POST with data to update


    """
    if request.method == "GET":
        try:
            message = DB.read("dm_messages", {"id": message_id})
            print(message)
            return Response(message)
        except:
            return JsonResponse(
                {"message": "The room does not exist"}, status=status.HTTP_404_NOT_FOUND
            )

    else:
        message = DB.read("dm_messages", {"id": message_id})
        room_serializer = MessageSerializer(
            message, data=request.data, partial=True)
        if room_serializer.is_valid():
            data = room_serializer.data
            data = {"message": request.data["message"]}
            # print(data)
            response = DB.update("dm_messages", message_id, data)
            if response.get("status") == 200:
                data = {
                    "sender_id": request.data["sender_id"],
                    "message_id": message_id,
                    "room_id": room_id,
                    "message": request.data["message"]
                    "event": "edited_message"
                }
                centrifugo_data = send_centrifugo_data(
                    room=room_id, data=data
                )

                    "event": "edited_message",
                }
                centrifugo_data = send_centrifugo_data(room=room_id, data=data)

                if centrifugo_data.get("error", None) == None:
                    return Response(data=data, status=status.HTTP_201_CREATED)
                return Response(data)
        return Response(room_serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@swagger_auto_schema(
    methods=["get"],
    operation_summary="Retrieves the link to a message",
    responses={
        200: MessageLinkResponse,
        400: "Error: Bad Request",
        404: "Error: This Message Does Not Exist",
    }
)
@api_view(["GET"])
@db_init_with_credentials
def copy_message_link(request, message_id):
    """
    Retrieves a single message using a message_id as query params.
    If message_id is provided, it returns a dictionary with information about the message,
    or a 204 status code if there is no message with the same message id.
    The message information returned is used to generate a link which contains a room_id and a message_id
    """
    if request.method == "GET":
        message = DB.read("dm_messages", {"id": message_id})
        room_id = message["room_id"]
        message_info = {
            "room_id": room_id,
            "message_id": message_id,
            "link": f"https://dm.zuri.chat/getmessage/{room_id}/{message_id}",
        }
        return Response(data=message_info, status=status.HTTP_200_OK)
    else:
        return Response(data="The message does not exist", status=status.HTTP_404_NOT_FOUND)


@api_view(["GET"])
@db_init_with_credentials
def read_message_link(request, room_id, message_id):
    """
    This is used to retrieve a single message. It takes a message_id as query params.
    or a 204 status code if there is no message with the same message id.
    I will use the message information returned to generate a link which contains a room_id and a message_id
    """

    if request.method == "GET":
        message = DB.read(
            "dm_messages", {"id": message_id, "room_id": room_id})
        return Response(data=message, status=status.HTTP_200_OK)
    else:
        return JsonResponse({'message': 'The message does not exist'}, status=status.HTTP_404_NOT_FOUND)


@swagger_auto_schema(
    methods=["get"],
    operation_summary="Retrieves all the links in a room",
    responses={
        200: GetLinksResponse,
        404: "Error: Message Not Found",
    }
)
@api_view(["GET"])
@db_init_with_credentials
def get_links(request, room_id):
    """
    Search messages in a room and return all links found
    Accepts room id as a param and queries the dm_messages collection for links attached to that id
    If no links were found, a 404 is returned
    """
    url_pattern = r"^(?:ht|f)tp[s]?://(?:www.)?.*$"
    regex = re.compile(url_pattern)
    matches = []
    messages = DB.read("dm_messages", filter={"room_id": room_id})
    if messages is not None:
        for message in messages:
            for word in message.get("message").split(" "):
                match = regex.match(word)
                if match:
                    matches.append(
                        {"link": str(word), "timestamp": message.get(
                            "created_at")}
                    )
        data = {"links": matches, "room_id": room_id}
        return Response(data=data, status=status.HTTP_200_OK)
    return Response(status=status.HTTP_404_NOT_FOUND)


@swagger_auto_schema(
    methods=["post"],
    request_body=BookmarkSerializer,
    operation_summary="Saves links as bookmarks in a room",
    responses={400: "Error: Bad Request"}
)
@api_view(["POST"])
@db_init_with_credentials
def save_bookmark(request, room_id):
    """
    Saves a link as a bookmark in a room
    It takes a room id as param and queries the dm_rooms collection
    Once room is found, it saves the link in the room as a list in the bookmark document
    """
    try:
        serializer = BookmarkSerializer(data=request.data)
        room = DB.read("dm_rooms", {"id": room_id})
        bookmarks = room["bookmarks"] or []
    except Exception as e:
        print(e)
        return Response(status=status.HTTP_503_SERVICE_UNAVAILABLE)
    if serializer.is_valid() and bookmarks is not None:
        bookmarks.append(serializer.data)
        data = {"bookmarks": bookmarks}
        response = DB.update("dm_rooms", room_id, data=data)
        if response.get("status") == 200:
            return Response(data=serializer.data, status=status.HTTP_200_OK)
    return Response(status=status.HTTP_400_BAD_REQUEST)


@swagger_auto_schema(
    methods=["post"],
    operation_summary="Retrieves all the members in an organization",
    request_body=CookieSerializer,
    responses={400: "Error: Bad Request"},
)
@api_view(["GET", "POST"])
@db_init_with_credentials
def organization_members(request):
    """
    Retrieves a list of all members in an organization.
    :returns: json response -> a list of objects (members) or 401_Unauthorized messages.

    GET: simulates production - if request is get, either token or cookie gotten from FE will be used,
    and authorization should take places automatically.

    POST: simulates testing - if request is post, send the cookies through the post request, it would be added
    manually to grant access, PS: please note cookies expire after a set time of inactivity.
    """
    ORG_ID = DB.organization_id

    url = f"https://api.zuri.chat/organizations/{ORG_ID}/members"

    if request.method == "GET":
        headers = {}

        if "Authorization" in request.headers:
            headers["Authorization"] = request.headers["Authorization"]
        else:
            headers["Cookie"] = request.headers["Cookie"]

        response = requests.get(url, headers=headers)

    elif request.method == "POST":
        cookie_serializer = CookieSerializer(data=request.data)

        if cookie_serializer.is_valid():
            cookie = cookie_serializer.data["cookie"]
            response = requests.get(url, headers={"Cookie": cookie})
        else:
            return Response(
                cookie_serializer.errors, status=status.HTTP_400_BAD_REQUEST
            )

    if response.status_code == 200:
        response = response.json()["data"]
        return Response(response, status=status.HTTP_200_OK)
    return Response(response.json(), status=status.HTTP_401_UNAUTHORIZED)


@swagger_auto_schema(
    methods=["get"],
    operation_summary="Retrieves all bookmarks in a room",
    responses={
        200: BookmarkResponse,
        400: "Error: Bad Request"
    }
)
@api_view(["GET"])
@db_init_with_credentials
def retrieve_bookmarks(request, room_id):
    """
    This endpoint retrieves all saved bookmarks in the room
    It takes a room id as param and queries the dm_rooms collection
    Once room is found, it retrieves all the bookmarked links in the room
    It then returns a json output of the links in a list
    """
    try:
        room = DB.read("dm_rooms", {"id": room_id})
        bookmarks = room["bookmarks"] or []
    except Exception as e:
        print(e)
        return Response(status=status.HTTP_503_SERVICE_UNAVAILABLE)
    if bookmarks is not None:
        serializer = BookmarkSerializer(data=bookmarks, many=True)
        if serializer.is_valid():
            return Response(data=serializer.data, status=status.HTTP_200_OK)
        return Response(status=status.HTTP_400_BAD_REQUEST)
    return Response(status=status.HTTP_404_NOT_FOUND)


@swagger_auto_schema(
    methods=["put"],
    operation_summary="Marks a message as read or unread",
    responses={
        200: "Ok: Success",
        400: "Error: Bad Request",
        503: "Server Error: Service Unavailable"
    }
)
@api_view(["PUT"])
@db_init_with_credentials
def mark_read(request, message_id):
    """
    Marks a message as read and unread
    Queries the dm_messages collection using a unique message id
    Checks read status of the message and updates the collection
    """
    try:
        message = DB.read("dm_messages", {"id": message_id})
        read = message["read"]
    except Exception as e:
        print(e)
        return Response(status=status.HTTP_503_SERVICE_UNAVAILABLE)
    data = {"read": not read}
    response = DB.update("dm_messages", message_id, data=data)
    message = DB.read("dm_messages", {"id": message_id})

    if response.get("status") == 200:
        return Response(data=data, status=status.HTTP_200_OK)
    return Response(status=status.HTTP_400_BAD_REQUEST)


@swagger_auto_schema(
    methods=["put"],
    operation_summary="Pins a message in a room",
    responses={
        200: PinMessageResponse,
        400: "Error: Bad Request",
        503: "Server Error: Service Unavailable",
    }
)
@api_view(["PUT"])
@db_init_with_credentials
def pinned_message(request, message_id):
    """
    This is used to pin a message.
    The message_id is passed to it which
    reads through the database, gets the room id,
    generates a link and then add it to the pinned key value.

    If the link already exist, it will unpin that particular message already pinned.
    """
    try:
        message = DB.read("dm_messages", {"id": message_id})
        if message:
            room_id = message["room_id"]
            room = DB.read("dm_rooms", {"id": room_id})
            pin = room["pinned"] or []
        else:
            return Response(status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        print(e)
        return Response(status=status.HTTP_503_SERVICE_UNAVAILABLE)
    if message_id in pin:
        pin.remove(message_id)

        data = {"message_id": message_id, "pinned": pin,
                "Event": "unpin_message"}  # this event key is in capslock

        data = {
            "message_id": message_id,
            "pinned": pin,
            "Event": "unpin_message",
        }  # this event key is in capslock

        response = DB.update("dm_rooms", room_id, {"pinned": pin})
        # room = DB.read("dm_rooms", {"id": room_id})
        if response["status"] == 200:
            centrifugo_data = send_centrifugo_data(
                room=room_id, data=data
            )  # publish data to centrifugo
            if centrifugo_data.get("error", None) == None:
                return Response(
                    data=data, status=status.HTTP_201_CREATED
                )
        else:
            return Response(status=response.status_code)
    else:
        pin.append(message_id)
        data = {"message_id": message_id,
                "pinned": pin,
                "Event": "pin_message"}
        response = DB.update("dm_rooms", room_id, {"pinned": pin})
        # room = DB.read("dm_rooms", {"id": room_id})
        centrifugo_data = send_centrifugo_data(
            room=room_id, data=data
        )  # publish data to centrifugo
        if centrifugo_data.get("error", None) == None:
            return Response(
                data=data, status=status.HTTP_201_CREATED
            )


@swagger_auto_schema(
    methods=["get"],
    operation_summary="Retreives messages in a room using a filter",
    responses={
        200: FilterMessageResponse,
        204: "Ok: No messages available",
        400: "Error: No such room or invalid Room",
    }
)
@api_view(["GET"])
@db_init_with_credentials
def message_filter(request, room_id):
    """
    Fetches all the messages in a room, and sort it out according to time_stamp.
    """
    if request.method == "GET":
        room = DB.read("dm_rooms", {"id": room_id})
        # room = "613b2db387708d9551acee3b"

        if room is not None:
            all_messages = DB.read("dm_messages", filter={"room_id": room_id})
            if all_messages is not None:
                message_timestamp_filter = sorted(
                    all_messages, key=lambda k: k["created_at"]
                )
                return Response(message_timestamp_filter, status=status.HTTP_200_OK)
            return Response(
                data="No messages available", status=status.HTTP_204_NO_CONTENT
            )
        return Response(
            data="No Room or Invalid Room", status=status.HTTP_400_BAD_REQUEST
        )


# @swagger_auto_schema(
#     methods=["delete"],
#     request_body=DeleteMessageSerializer,
#     responses={400: "Error: Bad Request"},
# )
# # @api_view(["DELETE"])
# # @db_init_with_credentials
# # def delete_message(request):
# #     """
# #     Deletes a message after taking the message id
# #     """

# #     if request.method == "DELETE":
# #         message_id = request.GET.get("message_id")
# #         message = DB.read("dm_messages", {"_id": message_id})
# #         if message:
# #             response = DB.delete("dm_messages", message_id)
# #             return Response(response, status.HTTP_200_OK)
# #         else:
# #             return Response("No such message", status.HTTP_404_NOT_FOUND)
# #     return Response(status.HTTP_405_METHOD_NOT_ALLOWED)


@swagger_auto_schema(
    methods=["get"],
    operation_summary="Retrieves the profile details of a user",
    responses={
        200: UserProfileResponse,
        401: "Error: Unauthorized Access",
        405: "Error: Method Not Allowed",
    }
)
@api_view(["GET"])
def user_profile(request, org_id, member_id):
    """
    Retrieves the user details of a member in an organization using a unique user_id
    If request is successful, a json output of select user details is returned
    Elif login session is expired or wrong details were entered, a 401 response is returned
    Else a 405 response returns if a wrong method was used
    Assume member_id is also the same as user_id in an org
    """

    url = f"https://api.zuri.chat/organizations/{org_id}/members/{member_id}"

    if request.method == "GET":
        header = {"Authorization": f"Bearer {login_user()}"}
        # print(request.headers)
        # if "Authorization" in request.headers:
        #     headers["Authorization"] = request.headers["Authorization"]
        # else:
        #     headers["Cookie"] = request.headers["Cookie"]
        response = requests.get(url, headers=header)

    else:
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    if response.status_code == 200:
        data = response.json()["data"]
        output = {
            "first_name": data["first_name"],
            "last_name": data["last_name"],
            "display_name": data["display_name"],
            "user_name": data["user_name"],
            "image_url": data["image_url"],
            "bio": data["bio"],
            "pronouns": data["pronouns"],
            "email": data["email"],
            "phone": data["phone"],
            "status": data["status"],
        }
        return Response(output, status=status.HTTP_200_OK)
    return Response(response.json(), status=status.HTTP_401_UNAUTHORIZED)


@swagger_auto_schema(
    methods=["post"],
    operation_summary="Creates message reminders in rooms",
    request_body=ReminderSerializer,
    responses={400: "Error: Bad Request"}
)
@api_view(["POST"])
def create_reminder(request):
    """
        This is used to remind a user about a  message
        Your body request should have the format
        {
        "message_id": "6146ea68845b436ea04d107d",
        "current_date": "Tue, 22 Nov 2011 06:00:00 GMT",
        "scheduled_date":"Tue, 22 Nov 2011 06:10:00 GMT",
        "notes": "fff"
    }
    """
    serializer = ReminderSerializer(data=request.data)
    if serializer.is_valid():
        serialized_data = serializer.data
        print(serialized_data)
        message_id = serialized_data["message_id"]
        current_date = serialized_data["current_date"]
        scheduled_date = serialized_data["scheduled_date"]
        try:
            notes_data = serialized_data["notes"]
        except:
            notes_data = ""

        # calculate duration and send notification
        local_scheduled_date = datetime.strptime(
            scheduled_date, '%a, %d %b %Y %H:%M:%S %Z')

        ##calculate duration and send notification
        local_scheduled_date = datetime.strptime(
            scheduled_date, "%a, %d %b %Y %H:%M:%S %Z"
        )

        utc_scheduled_date = local_scheduled_date.replace(tzinfo=timezone.utc)

        local_current_date = datetime.strptime(
            current_date, '%a, %d %b %Y %H:%M:%S %Z')
        utc_current_date = local_current_date.replace(tzinfo=timezone.utc)
        duration = local_scheduled_date - local_current_date
        duration_sec = duration.total_seconds()
        if duration_sec > 0:
            # get message infos , sender info and recpient info
            message = DB.read("dm_messages", {"id": message_id})
            if message:
                room_id = message['room_id']
                try:
                    room = DB.read("dm_rooms", {"_id": room_id})

                except Exception as e:
                    print(e)
                    return Response(status=status.HTTP_503_SERVICE_UNAVAILABLE)
                users_in_a_room = room.get("room_user_ids", []).copy()

                message_content = message['message']
                sender_id = message['sender_id']
                recipient_id = ''

                message_content = message["message"]
                sender_id = message["sender_id"]
                recipient_id = ""

                if sender_id in users_in_a_room:
                    users_in_a_room.remove(sender_id)
                    recipient_id = users_in_a_room[0]
                response_output = {
                    "recipient_id": recipient_id,
                    "sender_id": sender_id,
                    "message": message_content,
                    "scheduled_date": scheduled_date
                }
                if len(notes_data) > 0:
                    try:
                        notes = message["notes"] or []
                        notes.append(notes_data)
                        response = DB.update(
                            "dm_messages", message_id, {"notes": notes})
                    except Exception as e:
                        notes = []
                        notes.append(notes_data)
                        response = DB.update(
                            "dm_messages", message_id, {"notes": notes})
                    if response.get("status") == 200:
                        response_output["notes"] = notes

                        return Response(data=response_output, status=status.HTTP_201_CREATED)

                        return Response(
                            data=response_output, status=status.HTTP_201_CREATED
                        )

                # SendNotificationThread(duration,duration_sec,utc_scheduled_date, utc_current_date).start()
                return Response(data=response_output, status=status.HTTP_201_CREATED)
            return Response(data="No such message", status=status.HTTP_400_BAD_REQUEST)
        return Response(data="Your current date is ahead of the scheduled time. Are you plannig to go back in time?", status=status.HTTP_400_BAD_REQUEST)
    return Response(data="Bad Format ", status=status.HTTP_400_BAD_REQUEST)


# def reminder(request):

#     # posting data to zuri core after validation
#     plugin_id = PLUGIN_ID
#     org_id = ORGANIZATION_ID
#     coll_name = "reminders"

#     reminder = serializer.data
#     reminder['event_id'] = event_id
#     reminder['user_id'] = user_id

#     reminder_payload = {
#         "plugin_id": plugin_id,
#         "organization_id": org_id,
#         "collection_name": coll_name,
#         "bulk_write": False,
#         "object_id": "",
#         "filter": {},
#         "payload": reminder
#     }
#     url = 'https://api.zuri.chat/data/write'

#     try:
#         response = requests.post(url=url, json=reminder_payload)

#         if response.status_code == 201:
#             return Response(reminder, status=status.HTTP_201_CREATED)
#         else:
#             return Response({"error": response.json()['message']}, status=response.status_code)

#     except exceptions.ConnectionError as e:
#         return Response(str(e), status=status.HTTP_502_BAD_GATEWAY)


# @api_view(['GET'])
# # @permission_classes((UserIsAuthenticated, ))
# def reminder_list(request):
#     """
#         This gets a list of reminders set by the user
#         {
#             "user_id":" "
#         }
#     """
#     if request.method == "GET":
#         # getting data from zuri core
#         DB.read("dm_messages",)

#         try:
#             response = requests.get(url=url)
#             if response.status_code == 200:
#                 reminders_list = response.json()['data']
#                 return Response(reminders_list, status=status.HTTP_200_OK)
#             else:
#                 return Response({"error": response.json()["message"]}, status=response.status_code)
#         except exceptions.ConnectionError as e:
#             return Response(str(e), status=status.HTTP_502_BAD_GATEWAY)


# @api_view(['DELETE'])
# # @permission_classes((UserIsAuthenticated, ))
# def delete_reminder(request, id):
#     DB.delete(collection_name, document_id)

#     plugin_id = PLUGIN_ID
#     org_id = ORGANIZATION_ID
#     coll_name = "reminders"
#     if request.method == 'DELETE':
#         url = 'https://api.zuri.chat/data/delete'

#         payload = {
#             "plugin_id": plugin_id,
#             "organization_id": org_id,
#             "collection_name": coll_name,
#             "bulk_delete": False,
#             "object_id": id,
#             "filter": {}
#         }
#     try:
#         response = requests.post(url=url, json=payload)

#         if response.status_code == 200:
#             return Response({"message": "reminder successfully deleted"},
#                             status=status.HTTP_200_OK)
#         else:
#             return Response({"error": response.json()['message']}, status=response.status_code)

#     except exceptions.ConnectionError as e:
#         return Response(str(e), status=status.HTTP_502_BAD_GATEWAY)


class Files(APIView):
    parser_classes = (MultiPartParser, FormParser)


class SendFile(APIView):
    """
    This endpoint is a send message endpoint that can take files, upload them
    and return the urls to the uploaded files to the media list in the message
    serializer
    This endpoint uses form data
    The file must be passed in with the key "file"

    """

    parser_classes = (MultiPartParser, FormParser)

    @swagger_auto_schema(
        operation_summary="Sends files as messages in rooms",
        responses={
            201: "OK: File Created!",
        },
    )
    # @method_decorator(db_init_with_credentials)
    def post(self, request, room_id, org_id):
        print(request.FILES)
        if request.FILES:
            file_urls = []
            files = request.FILES.getlist('file')
            if len(files) == 1:
                for file in request.FILES.getlist('file'):
                    file_data = DB.upload(file)
                    if file_data["status"] == 200:
                        for datum in file_data["data"]['files_info']:
                            file_urls.append(datum['file_url'])
                    else:
                        return Response(file_data)
            elif len(files) > 1:
                multiple_files = []
                for file in files:
                    multiple_files.append(("file", file))
                file_data = DB.upload_more(multiple_files)
                if file_data["status"] == 200:
                    for datum in file_data["data"]['files_info']:
                        file_urls.append(datum['file_url'])
                else:
                    return Response(file_data)

            request.data["room_id"] = room_id
            print(request)
            serializer = MessageSerializer(data=request.data)

            if serializer.is_valid():
                data = serializer.data
                room_id = data["room_id"]  # room id gotten from client request

                room = DB.read("dm_rooms", {"_id": room_id})
                if room and room.get("status_code", None) == None:
                    if data["sender_id"] in room.get("room_user_ids", []):
                        data["media"] = file_urls
                        response = DB.write("dm_messages", data=data)
                        if response.get("status", None) == 200:

                            response_output = {
                                "status": response["message"],
                                "event": "message_create",
                                "message_id": response["data"]["object_id"],
                                "room_id": room_id,
                                "thread": False,
                                "data": {
                                    "sender_id": data["sender_id"],
                                    "message": data["message"],
                                    "created_at": data["created_at"],
                                    "media": data["media"],
                                },
                            }

                            try:
                                centrifugo_data = centrifugo_client.publish(
                                    room=room_id, data=response_output
                                )  # publish data to centrifugo
                                if (
                                    centrifugo_data
                                    and centrifugo_data.get("status_code") == 200
                                ):
                                    return Response(
                                        data=response_output,
                                        status=status.HTTP_201_CREATED,
                                    )
                                else:
                                    return Response(
                                        data="message not sent",
                                        status=status.HTTP_424_FAILED_DEPENDENCY,
                                    )
                            except:
                                return Response(
                                    data="centrifugo server not available",
                                    status=status.HTTP_424_FAILED_DEPENDENCY,
                                )
                        return Response(
                            data="message not saved and not sent",
                            status=status.HTTP_424_FAILED_DEPENDENCY,
                        )
                    return Response(
                        "sender not in room", status=status.HTTP_400_BAD_REQUEST
                    )
                return Response("room not found", status=status.HTTP_400_BAD_REQUEST)
            return Response(status=status.HTTP_400_BAD_REQUEST)


class Emoji(APIView):
    """
    List all Emoji reactions, or create a new Emoji reaction.
    """

    @swagger_auto_schema(
        operation_summary="Retrieves reactions to messages",
        responses={
            200: "OK: Success!",
            400: "Error: Bad Request",
        },
    )
    @method_decorator(db_init_with_credentials)
    def get(self, request, room_id: str, message_id: str):
        # fetch message related to that reaction
        message = DB.read(
            "dm_messages", {"_id": message_id, "room_id": room_id})
        if message:
            print(message)
            if response:
                return Response(
                    data={
                        "status": message["message"],
                        "event": "get_message_reactions",
                        "room_id": message["room_id"],
                        "message_id": message["_id"],
                        "data": {
                            "reactions": message["reactions"],
                        },
                    },
                    status=status.HTTP_200_OK,
                )
            return Response(
                data="Data not retrieved", status=status.HTTP_424_FAILED_DEPENDENCY
            )
        return Response("No such message or room", status=status.HTTP_404_NOT_FOUND)

    @swagger_auto_schema(
        request_body=EmojiSerializer,
        operation_summary="Creates and keeps tracks of reactions to messages",
        responses={
            201: "OK: Success!",
            400: "Error: Bad Request"},
    )
    @method_decorator(db_init_with_credentials)
    def post(self, request, room_id: str, message_id: str):
        request.data["message_id"] = message_id
        serializer = EmojiSerializer(data=request.data)
        if serializer.is_valid():
            data = serializer.data
            data["count"] += 1
            message_id = data["message_id"]
            sender_id = data["sender_id"]

            # fetch message related to that reaction
            message = DB.read(
                "dm_messages", {"_id": message_id, "room_id": room_id})
            if message:
                # get reactions
                reactions = message.get("reactions", [])
                reactions.append(data)

                room = DB.read(ROOMS, {"_id": message["room_id"]})
                if room:
                    # update reactions for a message
                    response = DB.update(MESSAGES, message_id, {
                                         "reactions": reactions})
                    if response.get("status", None) == 200:
                        response_output = {
                            "status": response["message"],
                            "event": "add_message_reaction",
                            "reaction_id": str(uuid.uuid1()),
                            "room_id": message["room_id"],
                            "message_id": message["_id"],
                            "data": {
                                "sender_id": sender_id,
                                "reaction": data["data"],
                                "created_at": data["created_at"],
                            },
                        }
                        centrifugo_data = centrifugo_client.publish(
                            room=message["room_id"], data=response_output
                        )  # publish data to centrifugo
                        if centrifugo_data["message"].get("error", None) == None:
                            return Response(
                                data=response_output, status=status.HTTP_201_CREATED
                            )
                    return Response(
                        "Data not sent", status=status.HTTP_424_FAILED_DEPENDENCY
                    )

                return Response("Unknown room", status=status.HTTP_404_NOT_FOUND)
            return Response(
                "Message or room not found", status=status.HTTP_404_NOT_FOUND
            )
        return Response(
            data=serializer.errors,
            status=status.HTTP_400_BAD_REQUEST,
        )


@swagger_auto_schema(
    methods=["post"],
    operation_summary="Schedules messages in rooms",
    request_body=ScheduleMessageSerializer,
    responses={
        201: "Success: Message Scheduled",
        400: "Error: Bad Request",
    },
)
@api_view(["POST"])
@db_init_with_credentials
def scheduled_messages(request, room_id):
    ORG_ID = DB.organization_id

    schedule_serializer = ScheduleMessageSerializer(data=request.data)
    if schedule_serializer.is_valid():
        data = schedule_serializer.data

        sender_id = data["sender_id"]
        room_id = data["room_id"]
        message = data["message"]
        timer = data["timer"]

        now = datetime.now()
        timer = datetime.strptime(timer, '%Y-%m-%d %H:%M:%S')
        duration = timer - now
        duration = duration.total_seconds()

        url = f"https://dm.zuri.chat/api/v1/org/{ORG_ID}/rooms/{room_id}/messages"
        payload = json.dumps({
            "sender_id": f"{sender_id}",
            "room_id": f"{room_id}",
            "message": f"{message}",
        })
        headers = {
            'Content-Type': 'application/json'
        }
        time.sleep(duration)
        response = requests.request("POST", url, headers=headers, data=payload)
    else:
        return Response(schedule_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    if response.status_code == 201:
        return Response(response.json(), status=status.HTTP_201_CREATED)
    return Response(response.json(), status=response.status_code)


# swagger documentation and function to delete message in rooms
@swagger_auto_schema(
    methods=["delete"],
    operation_summary="Deletes messages from rooms",
    request_body=DeleteMessageSerializer,
    responses={400: "Error: Bad Request"},
)
@api_view(["DELETE"])
@db_init_with_credentials
def delete_message(request, message_id, room_id):
    """
    This function deletes message in rooms using message 
    organization id (org_id), room id (room_id) and the message id (message_id).
    """
    message_id = request.GET.get("message_id")
    room_id = request.GET.get("room_id")
    if request.method == "DELETE":
        try:
            message = DB.read("dm_messages", {"_id": message_id})
            room = DB.read("dm_rooms", {"_id": room_id})

            if room and message:
                response = DB.delete("dm_messages", {"_id": message_id})
                centrifugo_data = centrifugo_client.publish(
                    message=message_id, data=response)
                if centrifugo_data and centrifugo_data.status_code == 200:
                    return Response(response, status=status.HTTP_200_OK)
            return Response("message not found", status=status.HTTP_404_NOT_FOUND)
        except exception_handler as e:
            return Response(str(e), status=status.HTTP_400_BAD_REQUEST)


@swagger_auto_schema(
    methods=["delete"],
    operation_summary="Deletes bookmarks from rooms",
    responses={
        200: "OK: Success",
        400: "Error: Bad Request",
        503: "Server Error: Service Unavailable",
    }
)
@api_view(["DELETE"])
@db_init_with_credentials
def delete_bookmark(request, room_id):
    """
    Deletes a saved bookmark in a room
    """
    try:
        room = DB.read("dm_rooms", {"id": room_id})
        bookmarks = room["bookmarks"] or []
    except Exception as e:
        print(e)
        return Response(status=status.HTTP_503_SERVICE_UNAVAILABLE)
    if bookmarks is not None:
        name = request.query_params.get("name", "")
        for bookmark in bookmarks:
            if name == bookmark.get("name", ""):
                bookmarks.remove(bookmark)
                break
        data = {"bookmarks": bookmarks}
        response = DB.update("dm_rooms", room_id, data=data)
        if response.get("status") == 200:
            return Response(status=status.HTTP_200_OK)
    return Response(status=status.HTTP_400_BAD_REQUEST)


@swagger_auto_schema(
    methods=["get"],
    operation_summary="searches for message by a user",
    responses={404: "Error: Not Found"},
)
@api_view(["GET"])
@db_init_with_credentials
def search_DM(request, member_id):


    keyword = request.query_params.get('keyword', "")
    users = request.query_params.getlist('id', [])
    limit = request.query_params.get('limit', 20)

    keyword = request.query_params.get("keyword", "")
    users = request.query_params.getlist("id", [])
    limit = request.query_params.get("limit", 20)

    try:
        if type(limit) == str:
            limit = int(limit)
    except ValueError:
        limit = 20

    paginator = PageNumberPagination()
    paginator.page_size = limit

    try:
        rooms = DB.read("dm_rooms")  # get all rooms

        user_rooms = list(filter(lambda room: member_id in room.get('room_user_ids', [
        ]) or member_id in room.get('room_member_ids', []), rooms))  # get all rooms with user

        user_rooms = list(
            filter(
                lambda room: member_id in room.get("room_user_ids", [])
                or member_id in room.get("room_member_ids", []),
                rooms,
            )
        )  # get all rooms with user

        if user_rooms != []:
            if users != []:
                rooms_checked = []
                for user in users:

                    rooms_checked += [room for room in user_rooms
                                      if set(room.get('room_user_ids', [])) == set([member_id, user]) or set(room.get('room_member_ids', [])) == set([member_id, user])]  # get rooms with other specified users

                    rooms_checked += [
                        room
                        for room in user_rooms
                        if set(room.get("room_user_ids", [])) == set([member_id, user])
                        or set(room.get("room_member_ids", []))
                        == set([member_id, user])
                    ]  # get rooms with other specified users

                user_rooms = rooms_checked
            all_messages = DB.read("dm_messages")  # get all messages
            thread_messages = []  # get all thread messages
            for message in all_messages:

                threads = message.get('threads', [])

                threads = message.get("threads", [])

                for thread in threads:
                    thread["room_id"] = message.get("room_id")
                    thread["message_id"] = message.get("_id")
                    thread["thread"] = True
                    thread_messages.append(thread)


            room_ids = [room['_id'] for room in user_rooms]

            user_rooms_messages = [message for message in all_messages
                                   if message['room_id'] in room_ids and message['message'].find(keyword) != -1]  # get message in rooms
            user_rooms_threads = [message for message in thread_messages
                                  if message['room_id'] in room_ids and message['message'].find(keyword) != -1]

            room_ids = [room["_id"] for room in user_rooms]

            user_rooms_messages = [
                message
                for message in all_messages
                if message["room_id"] in room_ids
                and message["message"].find(keyword) != -1
            ]  # get message in rooms
            user_rooms_threads = [
                message
                for message in thread_messages
                if message["room_id"] in room_ids
                and message["message"].find(keyword) != -1
            ]


            user_rooms_messages.extend(user_rooms_threads)
            if user_rooms_messages != []:
                for message in user_rooms_messages:

                    if 'read' in message.keys():
                        del message['read']
                    if 'pinned' in message.keys():
                        del message['pinned']
                    if 'saved_by' in message.keys():
                        del message['saved_by']
                    if 'threads' in message.keys():
                        del message['threads']
                    if 'thread' not in message.keys():
                        message['thread'] = False
                result_page = paginator.paginate_queryset(
                    user_rooms_messages, request)

                    if "read" in message.keys():
                        del message["read"]
                    if "pinned" in message.keys():
                        del message["pinned"]
                    if "saved_by" in message.keys():
                        del message["saved_by"]
                    if "threads" in message.keys():
                        del message["threads"]
                    if "thread" not in message.keys():
                        message["thread"] = False
                result_page = paginator.paginate_queryset(user_rooms_messages, request)

                return paginator.get_paginated_response(result_page)
        return Response([], status=status.HTTP_200_OK)
    except:
        return Response([], status=status.HTTP_200_OK)


@api_view(["GET"])
def PING(request):
    url = "https://api.zuri.chat"
    try:
        response = requests.get(
            url, headers={"Content-Type": "application/json"})
        server = {"server": True}
        return Response(data=server)
    except:
        server = {"server": False}
        return JsonResponse(data=server)


class ThreadListView(generics.ListCreateAPIView):
    """
    List all messages in thread, or create a new Thread message.
    """

    serializer_class = ThreadSerializer

    @swagger_auto_schema(
        operation_summary="Retrieves thread messages for a specific message",
        responses={
            200: "OK: Success!",
            400: "Error: Bad Request",
        },
    )
    # @method_decorator(db_init_with_credentials)
    def get(
        self,
        request,
        org_id: str,
        room_id: str,
        message_id: str,
    ) -> Response:
        """Retrieves all thread messages attached to a specific message

        Args:
            org_id (str): The organisation id
            room_id (str): The room id where the dm occured
            message_id (str): The message id for which we want to get the thread messages

        Returns:
            Response: Contains a list of thread messsages
        """
        # fetch message parent of the thread
        data_storage = DataStorage()
        data_storage.organization_id = org_id
        message = data_storage.read(

            "dm_messages", {"_id": message_id, "room_id": room_id})

            "dm_messages", {"_id": message_id, "room_id": room_id}
        )

        if message and message.get("status_code", None) == None:
            threads = message.get("threads")
            threads.reverse()
            return Response(
                data={
                    "room_id": message["room_id"],
                    "message_id": message["_id"],
                    "data": {
                        "threads": threads,
                    },
                },
                status=status.HTTP_200_OK,
            )

        return Response("No such message", status=status.HTTP_404_NOT_FOUND)

    @swagger_auto_schema(
        operation_summary="Create a thread message for a specific message",
        request_body=ThreadSerializer,
        responses={
            200: "OK: Success!",
            400: "Error: Bad Request",
        },
    )
    def post(
        self,
        request,
        org_id: str,
        room_id: str,
        message_id: str,
    ) -> Response:
        """
        Validates if the message exists, then sends
        a publish event to centrifugo after
        thread message is persisted.
        """

        data_storage = DataStorage()
        data_storage.organization_id = org_id
        request.data["message_id"] = message_id
        serializer = ThreadSerializer(data=request.data)

        if serializer.is_valid():
            data = serializer.data
            message_id = data["message_id"]
            sender_id = data["sender_id"]

            message = data_storage.read(
                MESSAGES, {"_id": message_id, "room_id": room_id}
            )  # fetch message from zc

            if message and message.get("status_code", None) == None:
                threads = message.get("threads", [])  # get threads
                # remove message id from request to zc core
                del data["message_id"]
                # assigns an id to each message in thread
                data["_id"] = str(uuid.uuid1())
                threads.append(data)  # append new message to list of thread

                room = data_storage.read(ROOMS, {"_id": message["room_id"]})
                if sender_id in room.get("room_user_ids", []):

                    response = data_storage.update(
                        MESSAGES, message["_id"], {"threads": threads}
                    )  # update threads in db
                    if response and response.get("status", None) == 200:

                        response_output = {
                            "status": response["message"],
                            "event": "thread_message_create",
                            "thread_id": data["_id"],
                            "room_id": message["room_id"],
                            "message_id": message["_id"],
                            "thread": True,
                            "data": {
                                "sender_id": data["sender_id"],
                                "message": data["message"],
                                "created_at": data["created_at"],
                            },
                        }

                        try:
                            centrifugo_data = centrifugo_client.publish(
                                room=room_id, data=response_output
                            )  # publish data to centrifugo
                            if (
                                centrifugo_data
                                and centrifugo_data.get("status_code") == 200
                            ):
                                return Response(
                                    data=response_output, status=status.HTTP_201_CREATED
                                )
                            else:
                                return Response(
                                    data="message not sent",
                                    status=status.HTTP_424_FAILED_DEPENDENCY,
                                )
                        except:
                            return Response(
                                data="centrifugo server not available",
                                status=status.HTTP_424_FAILED_DEPENDENCY,
                            )
                    return Response(
                        "data not sent", status=status.HTTP_424_FAILED_DEPENDENCY
                    )
                return Response("sender not in room", status=status.HTTP_404_NOT_FOUND)
            return Response(
                "message or room not found", status=status.HTTP_404_NOT_FOUND
            )
        return Response(status=status.HTTP_400_BAD_REQUEST)


class ThreadDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    Retrieve a single thread message, update a thread message or delete.
    """

    serializer_class = ThreadSerializer
    queryset = ""
    lookup_field = "thread_message_id"

    @swagger_auto_schema(
        operation_summary="Deletes a specifc thread message for a specific parent message",
        responses={
            200: "OK: Success!",
            400: "Error: Bad Request",
        },
    )
    def delete(
        self,
        request,
        org_id: str,
        room_id: str,
        message_id: str,
        thread_message_id: str,
    ) -> Response:
        """Deletes a specifc thread message for a specific parent message

        Args:
            request (Request): The incoming HTTP request
            org_id (str): The organisation id
            room_id (str): The room id where the dm occured
            message_id (str): The message id for which we want to get the thread messages
            thread_message_id (str): The thread message id to delete

        Returns:
            Response: Contains a new list of thread messsages
        """
        data_storage = DataStorage()
        data_storage.organization_id = org_id
        message = data_storage.read(
            MESSAGES, {"_id": message_id, "room_id": room_id})
        if message and message.get("status_code", None) == None:
            threads: List[Dict] = message.get("threads")
            if threads:
                for thread in threads:
                    # removes the specific thread message
                    if thread_message_id == thread.get("_id"):
                        threads.remove(thread)
                        break
                data = {"threads": threads}
                response = data_storage.update(MESSAGES, message_id, data=data)
                if response.get("status", None) == 200:
                    response_output = {
                        "status": response["message"],
                        "event": "thread_message_delete",
                        "thread_id": thread_message_id,
                        "room_id": room_id,
                        "message_id": message_id,
                        "data": {
                            "threads": threads,
                        },
                    }
                    try:
                        # publish data to centrifugo
                        centrifugo_data = centrifugo_client.publish(
                            room=room_id, data=response_output
                        )
                        if (
                            centrifugo_data
                            and centrifugo_data.get("status_code") == 200
                        ):
                            return Response(
                                data=response_output, status=status.HTTP_200_OK
                            )
                        else:
                            return Response(
                                data="Message not sent",
                                status=status.HTTP_424_FAILED_DEPENDENCY,
                            )
                    except:
                        return Response(
                            data="Centrifugo server not available",
                            status=status.HTTP_424_FAILED_DEPENDENCY,
                        )

        return Response(status=status.HTTP_400_BAD_REQUEST)

    def put(

            self,
            request,
            org_id: str,
            room_id: str,
            message_id: str,
            thread_message_id: str):

        self,
        request,
        org_id: str,
        room_id: str,
        message_id: str,
        thread_message_id: str,
    ):


        data_storage = DataStorage()
        data_storage.organization_id = org_id
        thread_serializer = ThreadSerializer(data=request.data)
        if thread_serializer.is_valid():
            thread_data = thread_serializer.data
            sender_id = thread_data["sender_id"]
            message_id = thread_data["message_id"]
            messages = data_storage.read("dm_messages", {"room_id": room_id})
            if messages:
                if "status_code" in messages:
                    if messages.get("status_code") == 404:
                        return Response(
                            data="No data on zc core", status=status.HTTP_404_NOT_FOUND
                        )
                    return Response(
                        data="Problem with zc core",
                        status=status.HTTP_424_FAILED_DEPENDENCY,
                    )
                for message in messages:
                    if message.get("_id") == message_id:
                        thread = message
                        break
                    thread = None
                if thread:
                    thread_messages = thread.get("threads", [])
                    for thread_message in thread_messages:
                        if thread_message.get("_id") == thread_message_id:
                            current_thread_message = thread_message
                            break
                        current_thread_message = None
                    if current_thread_message:
                        if (
                            current_thread_message["sender_id"] == sender_id
                            and thread["_id"] == message_id
                        ):
                            current_thread_message["message"] = thread_data["message"]
                            response = data_storage.update(
                                "dm_messages",
                                thread["_id"],
                                {"threads": thread_messages},
                            )
                            if response and response.get("status") == 200:
                                response_output = {
                                    "status": response["message"],
                                    "event": "thread_message_update",
                                    "thread_id": current_thread_message["_id"],
                                    "room_id": thread["room_id"],
                                    "message_id": thread["_id"],
                                    "thread": True,
                                    "data": {
                                        "sender_id": thread_data["sender_id"],
                                        "message": thread_data["message"],
                                        "created_at": thread_data["created_at"],
                                    },
                                    "edited": True,
                                }
                                try:
                                    centrifugo_data = centrifugo_client.publish(
                                        room=room_id, data=response_output
                                    )
                                    if (
                                        centrifugo_data
                                        and centrifugo_data.get("status_code") == 200
                                    ):
                                        return Response(
                                            data=response_output,
                                            status=status.HTTP_201_CREATED,
                                        )
                                    else:
                                        return Response(
                                            data="Message not sent",
                                            status=status.HTTP_424_FAILED_DEPENDENCY,
                                        )
                                except Exception:
                                    return Response(
                                        data="Centrifugo server not available",
                                        status=status.HTTP_424_FAILED_DEPENDENCY,
                                    )
                            return Response(
                                data="Message not updated",
                                status=status.HTTP_424_FAILED_DEPENDENCY,
                            )
                        return Response(
                            data="Sender_id or message_id invalid",
                            status=status.HTTP_400_BAD_REQUEST,
                        )
                    return Response(
                        data="Thread message not found",
                        status=status.HTTP_404_NOT_FOUND,
                    )
                return Response(
                    data="Message not found", status=status.HTTP_404_NOT_FOUND
                )
            return Response(data="Room not found", status=status.HTTP_404_NOT_FOUND)
        return Response(thread_serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ThreadEmoji(APIView):
    """
    List all Emoji reactions, or create a new Emoji reaction.
    """

    def get(

            self,
            request,
            org_id: str,
            room_id: str,
            message_id: str,
            thread_message_id: str):

        self,
        request,
        org_id: str,
        room_id: str,
        message_id: str,
        thread_message_id: str,
    ):


        data_storage = DataStorage()
        data_storage.organization_id = org_id
        message = data_storage.read(

            "dm_messages", {"_id": message_id, "room_id": room_id})

            "dm_messages", {"_id": message_id, "room_id": room_id}
        )

        if message:
            if "status_code" in message:
                return Response(
                    data="Unable to retrieve data from zc core",

                    status=status.HTTP_424_FAILED_DEPENDENCY
                )
            current_thread_message = [
                thread for thread in message["threads"] if thread["_id"] == thread_message_id]

                    status=status.HTTP_424_FAILED_DEPENDENCY,
                )
            current_thread_message = [
                thread
                for thread in message["threads"]
                if thread["_id"] == thread_message_id
            ]

            if current_thread_message:
                return Response(
                    data={
                        "status": "200",
                        "event": "get_thread_message_reactions",
                        "room_id": message["room_id"],
                        "message_id": message["_id"],
                        "thread_message_id": current_thread_message[0]["_id"],
                        "data": {
                            "reactions": current_thread_message[0]["reactions"],
                        },
                    },
                    status=status.HTTP_200_OK,
                )
            return Response(
                data="No such thread message", status=status.HTTP_404_NOT_FOUND
            )
        return Response("No such message or room", status=status.HTTP_404_NOT_FOUND)

    def post(
        self,
        request,
        org_id: str,
        room_id: str,
        message_id: str,
        thread_message_id: str,
    ):
        request.data["message_id"] = thread_message_id
        serializer = EmojiSerializer(data=request.data)

        if serializer.is_valid():
            data = serializer.data
            thread_message_id = data["message_id"]
            sender_id = data["sender_id"]
            data_storage = DataStorage()
            data_storage.organization_id = org_id

            # fetch message related to that reaction
            message = data_storage.read(

                "dm_messages", {"_id": message_id, "room_id": room_id})

                "dm_messages", {"_id": message_id, "room_id": room_id}
            )

            if message:
                if "status_code" in message:
                    return Response(
                        data="Unable to retrieve data from zc core",

                        status=status.HTTP_424_FAILED_DEPENDENCY
                    )
                # get reactions
                current_thread_message = [
                    thread for thread in message["threads"] if thread["_id"] == thread_message_id]

                        status=status.HTTP_424_FAILED_DEPENDENCY,
                    )
                # get reactions
                current_thread_message = [
                    thread
                    for thread in message["threads"]
                    if thread["_id"] == thread_message_id
                ]

                if current_thread_message:
                    reactions = current_thread_message[0].get("reactions", [])
                    data["_id"] = str(uuid.uuid1())
                    reactions.append(data)
                    # update reactions for a message

                    response = data_storage.update("dm_messages", message_id, {
                                                   "threads": message["threads"]})

                    response = data_storage.update(
                        "dm_messages", message_id, {"threads": message["threads"]}
                    )

                    if response.get("status", None) == 200:
                        response_output = {
                            "status": response["message"],
                            "event": "add_thread_message_reaction",
                            "reaction_id": data["_id"],
                            "parent_message_id": message["_id"],
                            "thread_message_id": current_thread_message[0]["_id"],
                            "data": {
                                "sender_id": sender_id,
                                "reaction": data["data"],
                                "created_at": data["created_at"],
                            },
                        }
                        centrifugo_data = centrifugo_client.publish(
                            room=message["room_id"], data=response_output
                        )  # publish data to centrifugo
                        if centrifugo_data["message"].get("error", None) == None:
                            return Response(
                                data=response_output, status=status.HTTP_201_CREATED
                            )
                        return Response(
                            data="Centrifugo server not available",

                            status=status.HTTP_424_FAILED_DEPENDENCY

                            status=status.HTTP_424_FAILED_DEPENDENCY,

                        )
                    return Response(
                        "Data not sent", status=status.HTTP_424_FAILED_DEPENDENCY
                    )
                return Response(
                    data="Not such thread message", status=status.HTTP_404_NOT_FOUND
                )
            return Response(
                "Message or room not found", status=status.HTTP_404_NOT_FOUND
            )
        return Response(
            data=serializer.errors,
            status=status.HTTP_400_BAD_REQUEST,
        )


@api_view(["DELETE"])
@db_init_with_credentials
def delete_thread_emoji_reaction(
    request, room_id, message_id, thread_message_id, reaction_id
):
    if request.method == "DELETE":
        message = DB.read(
            "dm_messages", {"_id": message_id, "room_id": room_id})
        if message:
            if "status_code" in message:
                return Response(
                    data="Unable to retrieve data from zc core",

                    status=status.HTTP_424_FAILED_DEPENDENCY
                )
            thread_message = [
                thread for thread in message["threads"] if thread["_id"] == thread_message_id]

                    status=status.HTTP_424_FAILED_DEPENDENCY,
                )
            thread_message = [
                thread
                for thread in message["threads"]
                if thread["_id"] == thread_message_id
            ]

            if thread_message:
                reactions = thread_message[0].get("reactions", [])
                for reaction in reactions:
                    try:
                        if reaction["_id"] == reaction_id:
                            emoji = reaction
                            break
                        emoji = None
                    except Exception:
                        pass
                if emoji:
                    reactions.remove(emoji)

                    response = DB.update("dm_messages", message_id, {
                                         "threads": message["threads"]})

                    response = DB.update(
                        "dm_messages", message_id, {"threads": message["threads"]}
                    )

                    if response.get("status", None) == 200:
                        response_output = {
                            "status": response["message"],
                            "event": "delete_thread_message_reaction",
                            "parent_message_id": message["_id"],
                            "data": {"response": "Reaction successfully deleted"},
                        }
                        centrifugo_data = centrifugo_client.publish(
                            room=message["room_id"], data=response_output
                        )  # publish data to centrifugo
                        if centrifugo_data["message"].get("error", None) == None:
                            return Response(
                                data=response_output, status=status.HTTP_201_CREATED
                            )
                        return Response(
                            data="Centrifugo server not available",

                            status=status.HTTP_424_FAILED_DEPENDENCY

                            status=status.HTTP_424_FAILED_DEPENDENCY,

                        )
                    return Response(
                        "Data not sent", status=status.HTTP_424_FAILED_DEPENDENCY
                    )
                return Response(
                    data="No such emoji reaction", status=status.HTTP_404_NOT_FOUND
                )
            return Response(
                data="No such thread message", status=status.HTTP_404_NOT_FOUND
            )
        return Response(
            data="Message or room not found", status=status.HTTP_404_NOT_FOUND
        )
    return Response(staus=status.HTTP_400_BAD_REQUEST)


@api_view(["PUT"])
@db_init_with_credentials
def update_thread_read_status(request, room_id, message_id, thread_message_id):
    if request.method == "PUT":
        message = DB.read(
            "dm_messages", {"_id": message_id, "room_id": room_id})
        if message:
            if "status_code" in message:
                if "status_code" == 404:
                    return Response(
                        data="No data on zc core", status=status.HTTP_404_NOT_FOUND
                    )
                return Response(
                    data="Problem with zc core",
                    status=status.HTTP_424_FAILED_DEPENDENCY,
                )
            else:
                thread_message = [

                    thread for thread in message["threads"] if thread["_id"] == thread_message_id]
                if thread_message:
                    thread_message[0]["read"] = not thread_message[0]["read"]
                    data = {"read": thread_message[0]["read"]}
                    response = DB.update("dm_messages", message_id, {
                                         "threads": message["threads"]})

                    thread
                    for thread in message["threads"]
                    if thread["_id"] == thread_message_id
                ]
                if thread_message:
                    thread_message[0]["read"] = not thread_message[0]["read"]
                    data = {"read": thread_message[0]["read"]}
                    response = DB.update(
                        "dm_messages", message_id, {"threads": message["threads"]}
                    )

                    if response and response.get("status") == 200:
                        return Response(data, status=status.HTTP_201_CREATED)
                    return Response(
                        data="Message status not updated",
                        status=status.HTTP_424_FAILED_DEPENDENCY,
                    )
                return Response(
                    data="Thread message not found", status=status.HTTP_404_NOT_FOUND
                )
        return Response(
            data="Parent message not found", status=status.HTTP_404_NOT_FOUND
        )
    return Response(status=status.HTTP_400_BAD_REQUEST)


@api_view(["POST"])
@db_init_with_credentials
def send_thread_message_to_channel(request, room_id, message_id, thread_message_id):
    if request.method == "POST":
        parent_message = DB.read(
            "dm_messages", {"_id": message_id, "room_id": room_id})
        if parent_message:
            if "status_code" in parent_message:
                if "status_code" == 404:

                    return Response(data="No data on zc core", status=status.HTTP_404_NOT_FOUND)
                return Response(data="Problem with zc core", status=status.HTTP_424_FAILED_DEPENDENCY)
            thread_message = [
                thread for thread in parent_message["threads"] if thread["_id"] == thread_message_id]

                    return Response(
                        data="No data on zc core", status=status.HTTP_404_NOT_FOUND
                    )
                return Response(
                    data="Problem with zc core",
                    status=status.HTTP_424_FAILED_DEPENDENCY,
                )
            thread_message = [
                thread
                for thread in parent_message["threads"]
                if thread["_id"] == thread_message_id
            ]

            if thread_message:
                sender_id = thread_message[0]["sender_id"]
                message = thread_message[0]["message"]
                url = f"https://dm.zuri.chat/api/v1/org/{DB.organization_id}/rooms/{room_id}/messages"
                payload = json.dumps(
                    {
                        "sender_id": f"{sender_id}",
                        "room_id": f"{room_id}",
                        "message": f"{message}",
                    }
                )
                headers = {"Content-Type": "application/json"}
                send_message = requests.request(

                    "POST", url, headers=headers, data=payload)

                    "POST", url, headers=headers, data=payload
                )

                if send_message.status_code == 201:
                    return Response(send_message.json(), status=status.HTTP_201_CREATED)
                return Response(send_message.json(), status=response.status_code)
            return Response(
                data="No thread message found", status=status.HTTP_404_NOT_FOUND
            )
        return Response(
            data="No message or room found", status=status.HTTP_404_NOT_FOUND
        )
    return Response(status=status.HTTP_400_BAD_REQUEST)


@api_view(["GET"])
@db_init_with_credentials
def copy_thread_message_link(request, room_id, message_id, thread_message_id):
    """
    Retrieves a single thread message using the thread_message_id as query params.
    The message information returned is used to generate a link which contains
    a room_id, parent_message_id and a thread_message_id
    """
    if request.method == "GET":
        parent_message = DB.read(
            "dm_messages", {"id": message_id, "room_id": room_id})
        if parent_message:
            if "status_code" in parent_message:
                if "status_code" == 404:

                    return Response(data="No data on zc core", status=status.HTTP_404_NOT_FOUND)
                return Response(data="Problem with zc core", status=status.HTTP_424_FAILED_DEPENDENCY)
            thread_message = [
                thread for thread in parent_message["threads"] if thread["_id"] == thread_message_id]

                    return Response(
                        data="No data on zc core", status=status.HTTP_404_NOT_FOUND
                    )
                return Response(
                    data="Problem with zc core",
                    status=status.HTTP_424_FAILED_DEPENDENCY,
                )
            thread_message = [
                thread
                for thread in parent_message["threads"]
                if thread["_id"] == thread_message_id
            ]

            if thread_message:
                message_info = {
                    "room_id": room_id,
                    "parent_message_id": message_id,
                    "thread_id": thread_message_id,
                    "link": f"https://dm.zuri.chat/thread_message/{DB.organization_id}/{room_id}/{message_id}/{thread_message_id}",
                }
                return Response(data=message_info, status=status.HTTP_200_OK)
            return Response(
                data="No such thread message", status=status.HTTP_404_NOT_FOUND
            )
        return Response(
            data="No parent message found", status=status.HTTP_404_NOT_FOUND
        )
    return Response(status=status.HTTP_400_BAD_REQUEST)


@api_view(["GET"])
@db_init_with_credentials
def read_thread_message_link(request, room_id, message_id, thread_message_id):
    if request.method == "GET":
        message = DB.read(
            "dm_messages", {"id": message_id, "room_id": room_id})
        if message:
            if "status_code" in message:
                if "status_code" == 404:

                    return Response(data="No data on zc core", status=status.HTTP_404_NOT_FOUND)
                return Response(data="Problem with zc core", status=status.HTTP_424_FAILED_DEPENDENCY)
            thread_message = [
                thread for thread in message["threads"] if thread["_id"] == thread_message_id]

                    return Response(
                        data="No data on zc core", status=status.HTTP_404_NOT_FOUND
                    )
                return Response(
                    data="Problem with zc core",
                    status=status.HTTP_424_FAILED_DEPENDENCY,
                )
            thread_message = [
                thread
                for thread in message["threads"]
                if thread["_id"] == thread_message_id
            ]

            if thread_message:
                return JsonResponse({"message": thread_message[0]["message"]})
            return Response(
                data="No such thread message", status=status.HTTP_404_NOT_FOUND
            )
        return Response(
            data="Parent message not found", status=status.HTTP_404_NOT_FOUND
        )
    return Response(status=status.HTTP_400_BAD_REQUEST)


@api_view(["PUT"])
@db_init_with_credentials
def pinned_thread_message(request, room_id, message_id, thread_message_id):
    message = DB.read("dm_messages", {"id": message_id, "room_id": room_id})
    if message:
        if "status_code" in message:
            if "status_code" == 404:
                return Response(
                    data="No data on zc core", status=status.HTTP_404_NOT_FOUND
                )
            return Response(
                data="Problem with zc core", status=status.HTTP_424_FAILED_DEPENDENCY
            )
        room = DB.read("dm_rooms", {"id": room_id})
        pin = room["pinned"] or []

        thread_message = [thread for thread in message["threads"]
                          if thread["_id"] == thread_message_id]
        if thread_message:
            pinned_thread_list = [
                thread_pin for thread_pin in pin if isinstance(thread_pin, dict)]
            pinned_thread_ids = [val.get("thread_message_id")
                                 for val in pinned_thread_list]
            if thread_message_id in pinned_thread_ids:
                current_pin = {key: value for (
                    key, value) in pinned_thread_list.items() if value == thread_message_id}
                pin.remove(current_pin)
                data = {"message_id": message_id, "thread_id": thread_message_id,
                        "pinned": pin, "Event": "unpin_thread_message"}

        thread_message = [
            thread
            for thread in message["threads"]
            if thread["_id"] == thread_message_id
        ]
        if thread_message:
            pinned_thread_list = [
                thread_pin for thread_pin in pin if isinstance(thread_pin, dict)
            ]
            pinned_thread_ids = [
                val.get("thread_message_id") for val in pinned_thread_list
            ]
            if thread_message_id in pinned_thread_ids:

                current_pin = {
                    key: value
                    for (key, value) in pinned_thread_list.items()
                    if value == thread_message_id
                }
                pin.remove(current_pin)
                data = {
                    "message_id": message_id,
                    "thread_id": thread_message_id,
                    "pinned": pin,
                    "Event": "unpin_thread_message",
                }

                response = DB.update("dm_rooms", room_id, {"pinned": pin})
                if response["status"] == 200:
                    centrifugo_data = send_centrifugo_data(
                        room=room_id, data=data
                    )  # publish data to centrifugo
                    if centrifugo_data.get("error", None) == None:
                        return Response(data=data, status=status.HTTP_201_CREATED)
                else:
                    return Response(status=response.status_code)
            else:

                current_pin = {"message_id": message_id,
                               "thread_message_id": thread_message_id}
                pin.append(current_pin)
                data = {"message_id": message_id, "thread_id": thread_message_id,
                        "pinned": pin, "Event": "pin_thread_message"}

                current_pin = {
                    "message_id": message_id,
                    "thread_message_id": thread_message_id,
                }
                pin.append(current_pin)
                data = {
                    "message_id": message_id,
                    "thread_id": thread_message_id,
                    "pinned": pin,
                    "Event": "pin_thread_message",
                }

                response = DB.update("dm_rooms", room_id, {"pinned": pin})
                centrifugo_data = send_centrifugo_data(
                    room=room_id, data=data
                )  # publish data to centrifugo
                if centrifugo_data.get("error", None) == None:
                    return Response(data=data, status=status.HTTP_201_CREATED)
        return Response(data="No such thread message", status=status.HTTP_404_NOT_FOUND)
    return Response(data="Parent message not found", status=status.HTTP_404_NOT_FOUND)


@api_view(["POST"])
@db_init_with_credentials
def send_reply(request, room_id, message_id):
    """
    This endpoint is used to send a reply message
    It takes in the a room_id and the message_id of the message being replied to
    Stores the data of the replied message in a field "replied message"
    """
    request.data["room_id"] = room_id
    print(request)
    serializer = MessageSerializer(data=request.data)
    reply_response = DB.read("dm_messages", {"_id": message_id})
    if reply_response and reply_response.get("status_code", None) == None:
        replied_message = reply_response
    else:
        return Response(
            "Message being replied to doesn't exist, FE pass in correct message id",
            status=status.HTTP_400_BAD_REQUEST,
        )
    print(reply_response)

    if serializer.is_valid():
        data = serializer.data
        room_id = data["room_id"]  # room id gotten from client request

        room = DB.read("dm_rooms", {"_id": room_id})
        if room and room.get("status_code", None) == None:
            if data["sender_id"] in room.get("room_user_ids", []):
                data["replied_message"] = replied_message
                response = DB.write("dm_messages", data=data)
                if response.get("status", None) == 200:

                    response_output = {
                        "status": response["message"],
                        "event": "message_create",
                        "message_id": response["data"]["object_id"],
                        "room_id": room_id,
                        "thread": False,
                        "data": {
                            "sender_id": data["sender_id"],
                            "message": data["message"],
                            "created_at": data["created_at"],
                            "replied_message": data["replied_message"],
                        },
                    }
                    try:
                        centrifugo_data = centrifugo_client.publish(
                            room=room_id, data=response_output
                        )  # publish data to centrifugo
                        if (
                            centrifugo_data
                            and centrifugo_data.get("status_code") == 200
                        ):
                            return Response(
                                data=response_output, status=status.HTTP_201_CREATED
                            )
                        else:
                            return Response(
                                data="message not sent",
                                status=status.HTTP_424_FAILED_DEPENDENCY,
                            )
                    except:
                        return Response(
                            data="centrifugo server not available",
                            status=status.HTTP_424_FAILED_DEPENDENCY,
                        )
                return Response(
                    data="message not saved and not sent",
                    status=status.HTTP_424_FAILED_DEPENDENCY,
                )
            return Response("sender not in room", status=status.HTTP_400_BAD_REQUEST)
        return Response("room not found", status=status.HTTP_400_BAD_REQUEST)
    return Response(status=status.HTTP_400_BAD_REQUEST)


def group_room(request, member_id):
    serializer = RoomSerializer(data=request.data)
    if serializer.is_valid():
        user_ids = serializer.data["room_member_ids"]


        if len(user_ids) > 9:
            response = {
                "get_group_data": True,
                "status_code": 400,
                "room_id": "Group cannot have over 9 total users"
            }
            return response
        else:
            all_rooms = DB.read("dm_rooms")
            group_rooms = []
            for room_obj in all_rooms:
                try:
                    room_members = room_obj['room_user_ids']
                    if len(room_members) > 2 and set(room_members) == set(user_ids):
                        group_rooms.append(room_obj['_id'])
                        response = {
                            "get_group_data": True,
                            "status_code": 200,
                            "room_id": room_obj["_id"]
                        }
                        return response
                except KeyError:
                    pass
                    # print("Object has no key of Serializer")

            # print("group rooms =", group_rooms)

            fields = {
                "org_id": serializer.data["org_id"],
                "room_user_ids": serializer.data["room_member_ids"],
                "room_name": serializer.data["room_name"],
                "private": serializer.data["private"],
                "created_at": serializer.data["created_at"],
                "bookmark": [],
                "pinned": [],
                "starred": []
            }
            response = DB.write("dm_rooms", data=fields)

        return response



        if len(user_ids) > 9:
            response = {
                "get_group_data": True,
                "status_code": 400,
                "room_id": "Group cannot have over 9 total users",
            }
            return response
        else:
            all_rooms = DB.read("dm_rooms")
            group_rooms = []
            for room_obj in all_rooms:
                try:
                    room_members = room_obj["room_user_ids"]
                    if len(room_members) > 2 and set(room_members) == set(user_ids):
                        group_rooms.append(room_obj["_id"])
                        response = {
                            "get_group_data": True,
                            "status_code": 200,
                            "room_id": room_obj["_id"],
                        }
                        return response
                except KeyError:
                    pass
                    # print("Object has no key of Serializer")

            # print("group rooms =", group_rooms)

            fields = {
                "org_id": serializer.data["org_id"],
                "room_user_ids": serializer.data["room_member_ids"],
                "room_name": serializer.data["room_name"],
                "private": serializer.data["private"],
                "created_at": serializer.data["created_at"],
                "bookmark": [],
                "pinned": [],
                "starred": [],
            }
            response = DB.write("dm_rooms", data=fields)

        return response


@api_view(["GET"])
@db_init_with_credentials
def get_all_threads(request, member_id: str):
    threads_list = LifoQueue()
    # org_id = request.GET.get("")

    if request.method == "GET":
        rooms = get_rooms(user_id=member_id, org_id=DB.organization_id)
        if rooms:
            # print(f"the room ", rooms)
            for room in rooms:
                # print(f"the room ", room)
                data = {}
                data["room_id"] = room.get("_id")
                data["room_name"] = room.get("room_name")
                messages = DB.read(MESSAGES, {"room_id": room.get("_id")})
                if messages:
                    if messages.get("status_code") == 404:
                        return Response(
                            data="No message in this room",
                            status=status.HTTP_404_NOT_FOUND,
                        )
                    # print(f"mrssages ", messages)
                    for message in messages:
                        threads = message.get("threads")
                        if threads:
                            print(threads)
                        return Response(
                            data="No threads found", status=status.HTTP_204_NO_CONTENT
                        )
                threads_list.put(data)
                print(f"lst qur", threads_list)
                return Response(
                    data="No messages found", status=status.HTTP_204_NO_CONTENT
                )

        return Response(data="No rooms created yet", status=status.HTTP_204_NO_CONTENT)

    return Response(status=status.HTTP_400_BAD_REQUEST)


@api_view(["PUT","GET"])
@db_init_with_credentials
def star_room(request, room_id, member_id):
    """
    Endpoint for starring and unstarring a user, it moves the user from the dm list to a starred dm list
    """
    if request.method == "PUT":
        room = DB.read("dm_rooms", {"_id": room_id})
        if room:

            if member_id in room.get("room_member_ids", []) or member_id in room.get("room_user_ids", []):

            if member_id in room.get("room_member_ids", []) or member_id in room.get(
                "room_user_ids", []
            ):

                data = room.get("starred", [])
                if member_id in data:
                    data.remove(member_id)
                else:
                    data.append(member_id)

                response = DB.update("dm_rooms", room_id, {"starred": data})
                print(response)

                if response and response.get("status_code", None) == None:
                    return Response("Sucess", status=status.HTTP_200_OK)

                if response and response.get("status_code",None) == None:
                    return Response("Success", status=status.HTTP_200_OK)

                return Response(data="Room not updated", status=status.HTTP_424_FAILED_DEPENDENCY)
            return Response(data="User not in room", status=status.HTTP_404_NOT_FOUND)
        return Response("Invalid room", status=status.HTTP_400_BAD_REQUEST)

    
    elif request.method == "GET":
        room = DB.read("dm_rooms", {"_id": room_id})
        if room:
            if member_id in room.get("room_member_ids", []) or member_id in room.get("room_user_ids", []):
                data =  room.get("starred",[])
                if member_id in data:
                   return Response({"status":True}, status=status.HTTP_200_OK)
                return Response({"status":False}, status=status.HTTP_200_OK)
            return Response(data="User not in room", status=status.HTTP_404_NOT_FOUND)                     
        return Response("Invalid room", status=status.HTTP_400_BAD_REQUEST)
    return Response(status=status.HTTP_400_BAD_REQUEST)



@api_view(["GET"])
def create_jwt_token(request, org_id, member_id):
    """
    This function takes member id (member_id)
    checks if such user is a member of the organization
    If the user is a member, then a token would be generated
    with the user id so as to be able to access any endpoint of the DM plugin
    """
    if request.method == "GET":
        org_id = request.query_params.get("org_id")
        if org_id is not None:
            print(org_id)
            member_id = org_id["member_id"]
            if member_id is not None:
                print(member_id)
                user_token = RefreshToken.for_user(member_id)
                user_access = {
                    "refresh": str(user_token),
                    "access": str(user_token.access_token)
                }
                print(user_access)
                return Response(data=user_access, status=status.HTTP_201_CREATED)
            return Response({"message": "user not found in this organization"}, status=status.HTTP_404_NOT_FOUND)
        return Response({"message": "This organization does not exist"}, status=status.HTTP_404_NOT_FOUND)

@api_view(["PUT"])
@db_init_with_credentials
def close_conversation(request, room_id, member_id):
    if request.method == "PUT":
        room = DB.read("dm_rooms", {"_id":room_id})
        if room or room is not None :
            room_users=room['room_user_ids']
            if member_id in room_users:
                room_users.remove(member_id)
                print(room_users)
                data = {'room_user_ids':room_users}
                print(data)
                response = DB.update("dm_rooms", room_id, data=data)
                return Response(response, status=status.HTTP_200_OK)
            return Response("You are not authorized", status=status.HTTP_401_UNAUTHORIZED)
        return Response("No Room / Invalid Room", status=status.HTTP_404_NOT_FOUND)
    return Response("Method Not Allowed", status=status.HTTP_405_METHOD_NOT_ALLOWED)

