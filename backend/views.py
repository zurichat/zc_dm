from django.http.response import JsonResponse
from django.shortcuts import render
from rest_framework.parsers import JSONParser
from django.http import HttpResponse
from rest_framework.decorators import api_view

from rest_framework.response import Response
from rest_framework import status
from rest_framework.views import APIView
import requests
# Import Read Write function to Zuri Core
from .db import DB



def index(request):
    context = {}
    return render(request, 'index.html', context)

# Shows basic information about the DM plugin
def info(request):
    info = {
        "message": "Plugin Information Retrieved",
        "data": {
            "type": "Plugin Information",
            "plugin_info": {"name": "DM Plugin",
                            "description": ["Zuri.chat plugin", "DM plugin for Zuri Chat that enables users to send messages to each other"]
                            },
            "scaffold_structure": "Monolith",
            "team": "HNG 8.0/Team Orpheus",
            "sidebar_url": "https://dm.zuri.chat/api/v1/sidebar",
            "homepage_url": "https://dm.zuri.chat/"
        },
        "success": "true"
    }

    return JsonResponse(info, safe=False)

 
def verify_user_auth(ID, token):
	url = f"https://api.zuri.chat/users/{ID}"
	headers = {
		'Authorization': f'Bearer {token}',
		'Content-Type': 'application/json'
	}
	response = requests.request("GET", url, headers=headers)
	
	return response.status == "200"


# Returns the json data of the sidebar that will be consumed by the api
# The sidebar info will be unique for each logged in user
# user_id will be gotten from the logged in user
# All data in the message_rooms will be automatically generated from zuri core
def side_bar(request):
    side_bar = {
        "name" : "DM Plugin",
        "description" : "Sends messages between users",
        "plugin_id" : "dm-plugin-id",
        "organisation_id" : "HNGi8",
        "user_id" : "232",
        "group_name" : "DM",
        "show_group" : False,
        # List of rooms/collections created whenever a user starts a DM chat with another user
        # This is what will be displayed by Zuri Main on the sidebar
        "message_rooms":[
            {
                "room_id":"collection_id",
                "partner":"username of chat-partner",
                "room_url":"https://dm.zuri.chat/api/organizations/id/rooms/id",
                "status":"active",
                "latest_message":"unread",
            },
            {
                "room_id":"collection_id",
                "partner":"username of chat-partner",
                "room_url":"https://dm.zuri.chat/api/organizations/id/rooms/id",
                "status":"active",
                "latest_message":"unread",
            },
            {
                "room_id":"collection_id",
                "partner":"username of chat-partner",
                "room_url":"https://dm.zuri.chat/api/organizations/id/rooms/id",
                "status":"active",
                "latest_message":"unread",
            },
            {
                "room_id":"collection_id",
                "partner":"username of chat-partner",
                "room_url":"https://dm.zuri.chat/api/organizations/id/rooms/id",
                "status":"active",
                "latest_message":"unread",
            },
            {
                "room_id":"collection_id",
                "partner":"username of chat-partner",
                "room_url":"https://dm.zuri.chat/api/organizations/id/rooms/id",
                "status":"active",
                "latest_message":"read",
            },
            {
                "room_id":"collection_id",
                "partner":"username of chat-partner",
                "room_url":"https://dm.zuri.chat/api/organizations/id/rooms/id",
                "status":"deleted",
                "latest_message":"read",
            },
            {
                "room_id":"collection_id",
                "partner":"username of chat-partner",
                "room_url":"https://dm.zuri.chat/api/organizations/id/rooms/id",
                "status":"deleted",
                "latest_message":"read",
            },
            {
                "room_id":"collection_id",
                "partner":"username of chat-partner",
                "room_url":"https://dm.zuri.chat/api/organizations/id/rooms/id",
                "status":"deleted",
                "latest_message":"read",
            },
        ],
    }
    return JsonResponse(side_bar, safe=False)





def organization(request):
    return render(request, "index.html")

def organizations(request):
    return render(request, "index.html")


def user(request):
    return render(request, "index.html")

def users(request):
    return render(request, "index.html")


def rooms(request):
    return render(request, "index.html")


def room(request):
    # return render(request, "index.html")
    return HttpResponse("<h1>Work in Progress</h1>")


def room_users(request):
    return render(request, "index.html")


def room_messages(request):
    return render(request, "index.html")


def room_message(request):
    return render(request, "index.html")


def room_medias(request):
    return render(request, "index.html")


def room_media(request):
    return render(request, "index.html")


def room_files(request):
    return render(request, "index.html")


def room_file(request):
    return render(request, "index.html")
