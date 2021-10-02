from . import views
from .testingapi import Test

# from .views import EditMessage
from django.urls import path
from django.conf import settings
from django.conf.urls.static import static
from django.conf import settings

urlpatterns = [
    path("", views.index, name="index"),
    path("api/v1/ping", views.PING, name="ping"),
    path("api/v1/info", views.info, name="plugin_info"),
    path("api/v1/sidebar", views.side_bar, name="sidebar"),

    path(
        "api/v1/org/<str:org_id>/members/<str:member_id>/messages/search", 
         views.search_DM,
         name="search DM"
    ),
    path(
        "api/v1/org/<str:org_id>/rooms/<str:room_id>/messages",  
         views.message_create_get,
         name="create_get_message"
    ),
    # path(
    #     "api/v1/org/<str:org_id>/rooms/<str:room_id>/messages/<str:message_id>/threads/<str:message_uuid>",
    #     views.update_thread_message,
    #     name="update_thread_message",
    # ),
    path(
        "api/v1/org/<str:org_id>/room",
        views.create_room,
        name="create_room"
    ),
    path(
        "api/v1/org/<str:org_id>/updatemessage/<str:pk>",
        views.edit_room,
        name="updateroom",
    ),
    path(
        "api/v1/org/<str:org_id>/rooms/<str:room_id>/info",
        views.room_info,
        name="room_info",
    ),
    path(
        "api/v1/org/<str:org_id>/users/<str:user_id>/rooms",
        views.user_rooms,
        name="get_user_rooms",
    ),
    path(  # what is this endpoint doing?
        "api/v1/org/<str:org_id>/reminder",
        views.remind_message,
        name="reminder",
    ),
    path(
        "api/v1/org/<str:org_id>/messages/<str:message_id>/link",
        views.copy_message_link,
        name="copy_message_link",
    ),
    path(  # review needed
        "getmessage/<str:room_id>/<str:message_id>",
        views.read_message_link,
        name="read_message_link",
    ),
    path(
        "api/v1/org/<str:org_id>/rooms/<str:room_id>/links",
        views.get_links,
        name="get_links",
    ),
    path(
        "api/v1/org/<str:org_id>/rooms/<str:room_id>/new-bookmark",
        views.save_bookmark,
        name="create_bookmark",
    ),
    path(
        "api/v1/org/<str:org_id>/members",
        views.organization_members,
        name="organization_members",
    ),
    path(
        "api/v1/org/<str:org_id>/rooms/<str:room_id>/bookmarks",
        views.retrieve_bookmarks,
        name="get_bookmarks",
    ),
    path( 
        "api/v1/org/<str:org_id>/messages/<str:message_id>/read",
        views.mark_read,
        name="mark_read",
    ),
    path(  # might require a room id
        "api/v1/org/<str:org_id>/messages/<str:message_id>/pin",
        views.pinned_message,
        name="pin_message",
    ),
    # path( #???
    #     "api/v1/<str:org_id>/messages/<str:message_id>/unpin",
    #     views.delete_pinned_message,
    #     name="unpin_message",
    # ),
    path(  # review needed
        "api/v1/<str:org_id>/<str:room_id>/<str:message_id>/pinnedmessage/",
        views.read_message_link,
        name="read_pinned_message",
    ),
    path(  # review needed???
        "api/v1/<str:org_id>/<str:room_id>/filter_messages",
        views.message_filter,
        name="message_filter",
    ),
    path(
        "api/v1/org/<str:org_id>/rooms/<str:room_id>/messages/<str:message_id>/message",
        views.delete_message,
        name="delete_message",
    ),
    path(
        "api/v1/org/<str:org_id>/members/<str:member_id>/profile",
        views.user_profile,
        name="user_profile",
    ),
    path( 
        "api/v1/org/<str:org_id>/rooms/<str:room_id>/messagemedia",
        views.SendFile.as_view(),
        name="media_files",
    ),
    path(
        "api/v1/org/<str:org_id>/rooms/<str:room_id>/messages/<str:message_id>/reactions",
        views.Emoji.as_view(),
        name="message_reactions",
    ),
    path(
        "api/v1/org/<str:org_id>/rooms/<str:room_id>/schedule-message",
        views.scheduled_messages,
        name="scheduled_messages",
    ),
    path(
        "api/v1/org/<str:org_id>/rooms/<str:room_id>/bookmark",
        views.delete_bookmark,
        name="delete_bookmark",
    ),
    path(
        "api/v1/org/<str:org_id>/rooms/<str:room_id>/messages/<str:message_id>/threads",
        views.ThreadListView.as_view(),
        name="messages_thread_list",
    ),
    path(
        "api/v1/org/<str:org_id>/rooms/<str:room_id>/messages/<str:message_id>/threads/<str:thread_message_id>",
        views.ThreadDetailView.as_view(),
        name="messages_thread_detail",
    ),
    path(
        "api/v1/org/<str:org_id>/rooms/<str:room_id>/messages/<str:message_id>/threads/<str:thread_message_id>/reactions",
        views.ThreadEmoji.as_view(),
        name="message_thread_reaction",
    ),
] + static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)


if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
