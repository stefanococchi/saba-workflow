#!/usr/bin/env python3
"""Create superuser for Saba Workflow admin"""
import sys
import getpass
from app import create_app
from app.models import User

app = create_app()

with app.app_context():
    from app import db_session as db
    username = input('Username: ').strip()
    if not username:
        print('Username required')
        sys.exit(1)

    if db.query(User).filter_by(username=username).first():
        print(f'User "{username}" already exists')
        sys.exit(1)

    email = input('Email (optional): ').strip() or None
    password = getpass.getpass('Password: ')
    if len(password) < 6:
        print('Password must be at least 6 characters')
        sys.exit(1)
    confirm = getpass.getpass('Confirm password: ')
    if password != confirm:
        print('Passwords do not match')
        sys.exit(1)

    user = User(username=username, email=email, is_superuser=True)
    user.set_password(password)
    db.add(user)
    db.commit()
    print(f'Superuser "{username}" created successfully')
