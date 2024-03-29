from uuid import uuid1
from config import Config_is
from constants import IMAGE_EXTENSION
from flask import render_template, g
from .utils import email_validation
from .sendgrid_email import send_email
from .crud import CRUD
from .custom_errors import (Forbidden, Conflict, InternalError, BadRequest, NoContent)
from app import db
from .aws_services import AmazonServices
from app.models import User, remove_user_token


def sent_email_invitation(first_name: str, last_name: str, to_email: str, auth_token: str) -> bool:
    """
    Sent email invitation to new users with signup link
    """
    invitation_html = render_template("user_invitation.html", first_name=first_name,
                                      registration_url=f"{Config_is.FRONT_END_REGISTRATION_URL}/{auth_token}?first_name={first_name}&last_name={last_name}")
    if send_email(to_email=to_email, html_content=invitation_html, subject="ABCD app Invitation"):
        return True
    raise InternalError("Please try again later.")


def adding_new_user(data: dict) -> str:
    """
    Adding new user and sent email invitation
    """
    data['email'] = data['email'].strip().lower()
    email_validation(data['email'])
    u = User.query.filter_by(email=data['email']).first()
    if not u:
        u = CRUD.create(User, {'organization_id': g.user['organization_id'], **data})
    elif u.is_deleted or not u.is_active:
        pass
    elif u.registered:
        raise Conflict('The user has already registered')
    token = u.generate_auth_token()  # token expires after 12 hours
    sent_email_invitation(u.first_name, u.last_name, u.email, token)
    CRUD.update(User, {'email': data['email']},
                {'is_active': True, 'registered': False, 'is_deleted': False, 'is_invited': True, **data})
    return token


def upload_user_profile_pic(file_is: object, user_obj: object) -> str:
    """
    Upload user avatar and remove if an image already exist
    """
    amazon = AmazonServices()
    file_extension = file_is.filename.split(".")[-1].upper()
    if user_obj.avatar:
        amazon.delete_s3_object(path=f"{user_obj.organization_id}/avatar/{user_obj.avatar}")
    if file_extension not in IMAGE_EXTENSION:
        raise BadRequest("Invalid file extension")
    new_file_name = f"{uuid1().hex}.{file_is.filename.split('.')[-1]}"
    amazon.file_upload_obj_s3(file_is, f"{user_obj.organization_id}/avatar/{new_file_name}")
    return new_file_name


def user_avatar_uploading(file_is: object = None):
    amazon = AmazonServices()
    user_obj = User.query.filter_by(id=g.user['id'], organization_id=g.user['organization_id']).first()
    if user_obj.avatar:
        amazon.delete_s3_object(path=f"{user_obj.organization_id}/avatar/{user_obj.avatar}")
    if file_is:
        avatar = amazon.upload_user_profile_pic(file_is['file'], user_obj)
        if avatar:
            user_obj.avatar = avatar
            CRUD.db_commit()
            return avatar
        raise BadRequest()
    return True


def user_avatar_deleting():
    user_obj = User.query.filter_by(id=g.user['id'], organization_id=g.user['organization_id']).first()
    if user_obj.avatar:
        AmazonServices().delete_s3_object(path=f"{user_obj.organization_id}/avatar/{user_obj.avatar}")
        CRUD.db_commit()
    return True


def edit_user_details(user_id: int, data: dict) -> bool:
    if data.get('role_id') and g.user['role_id'] != 2:
        raise Forbidden()
    CRUD.update(User, {'id': user_id}, data)
    return True


def make_user_active_inactive(user_id: int, is_active: bool) -> bool:
    if g.user['id'] == user_id:
        raise Forbidden()
    user_obj = User.query.filter_by(id=user_id, organization_id=g.user['organization_id']).first()
    if is_active:
        user_obj.is_active = True
        CRUD.db_commit()
    else:
        remove_user_token(user_id)
    return True


def delete_organization_user(user_id):
    u = User.query.filter_by(id=user_id, organization_id=g.user['organization_id']).first()
    if user_id == g.user['id']:
        raise Forbidden()
    if u:
        remove_user_token(user_id)
        db.session.delete(u)
        CRUD.db_commit()
        return True
    raise NoContent()
