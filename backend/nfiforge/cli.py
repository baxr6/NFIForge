# account commands for the installer and admins: nfiforge user add|list|password|remove, nfiforge pair <user>.
# passwords come from NFIFORGE_PASSWORD or a prompt, never the command line (it shows in process lists)

from __future__ import annotations

import getpass
import os
import shutil
import subprocess
import sys

from nfiforge.auth import PAIR_MINUTES, ROLES, hash_password, new_secret, password_problem, username_problem
from nfiforge.setup import reachable, serve_urls
from nfiforge.store import Store


def _password() -> str:
  password = os.environ.get("NFIFORGE_PASSWORD")
  if password is None:
    password = getpass.getpass("password: ")
    if getpass.getpass("again: ") != password:
      sys.exit("passwords don't match")
  if problem := password_problem(password):
    sys.exit(problem)
  return password


def _user(db: Store, name: str) -> dict:
  user = db.user_by_name(name)
  if not user:
    sys.exit(f"no user called {name}")
  return user


def add_user(db: Store, name: str, role: str) -> None:
  if problem := username_problem(name):
    sys.exit(problem)
  if role not in ROLES:
    sys.exit("role: admin or viewer")
  if db.user_by_name(name):
    sys.exit(f"{name} already exists")
  db.add_user(name, hash_password(_password()), role)
  print(f"added {name} ({role})")


def run(args, config) -> None:
  db = Store(config.data_dir)
  if args.cmd == "pair":
    user = _user(db, args.username)
    code, code_hash = new_secret()
    db.add_pair(code_hash, user["id"], PAIR_MINUTES)
    if not args.link:
      print(code)
      return
    bases = serve_urls(config.port) + [f"http://{host}:{config.port}" for host in reachable(config)]
    links = [f"{base}/?pair={code}" for base in bases]
    if not links:
      sys.exit("the dashboard only opens on this computer; run nfiforge init again and pick Tailscale or your network")
    if shutil.which("qrencode"):  # scan the first (preferred) link
      subprocess.run(["qrencode", "-t", "ANSIUTF8", "-m", "2", links[0]], check=False)
    for link in links:
      print(link)
    print(f"works once, for {PAIR_MINUTES} minutes; the phone stays signed in as {user['username']} after")
    return
  if args.action == "list":
    for user in db.users():
      print(f"{user['username']:20} {user['role']:7} {'disabled' if user['disabled'] else ''}")
  elif args.action == "add":
    add_user(db, args.username, args.role)
  elif args.action == "password":
    user = _user(db, args.username)
    db.update_user(user["id"], pw=hash_password(_password()))
    db.end_sessions(user["id"])
    print(f"password changed for {args.username}; signed out everywhere")
  elif args.action == "remove":
    user = _user(db, args.username)
    if user["role"] == "admin" and db.admins() <= 1:
      sys.exit("there must be at least one admin")
    db.delete_user(user["id"])
    print(f"removed {args.username}")
