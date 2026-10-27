"""Concurrent writes use only disposable SQLite files, never learning.db."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
from threading import Barrier
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import AdminAuditLog, User
from app.services.admin import bootstrap_admin, set_user_status


class AdminConcurrencyTest(unittest.TestCase):
    def test_two_admins_cannot_disable_each_other_simultaneously(self):
        with tempfile.TemporaryDirectory() as folder:
            engine=create_engine("sqlite:///"+(Path(folder)/"race.db").as_posix(),connect_args={"check_same_thread":False,"timeout":10})
            try:
                Base.metadata.create_all(engine)
                factory=sessionmaker(bind=engine)
                with factory() as db:
                    db.add_all([User(username=name,password_hash="hash",role="admin") for name in ["first","second"]]);db.commit()
                barrier=Barrier(2)
                def disable(actor,target):
                    with factory() as db:
                        barrier.wait(timeout=5)
                        try:
                            set_user_status(db,actor,0,target,False)
                            return 200
                        except HTTPException as error:
                            return error.status_code
                with ThreadPoolExecutor(max_workers=2) as pool:
                    a=pool.submit(disable,1,2);b=pool.submit(disable,2,1)
                    self.assertEqual(sorted([a.result(timeout=15),b.result(timeout=15)]),[200,401])
                with factory() as db:
                    self.assertEqual(db.query(User).filter_by(role="admin",is_active=True).count(),1)
                    self.assertEqual(db.query(AdminAuditLog).count(),1)
            finally:
                engine.dispose()

    def test_parallel_bootstrap_creates_exactly_one_admin(self):
        with tempfile.TemporaryDirectory() as folder:
            engine=create_engine("sqlite:///"+(Path(folder)/"init.db").as_posix(),connect_args={"check_same_thread":False,"timeout":10})
            try:
                Base.metadata.create_all(engine);factory=sessionmaker(bind=engine);barrier=Barrier(2)
                def initialize(name):
                    with factory() as db:
                        barrier.wait(timeout=5)
                        try:
                            bootstrap_admin(db,name,"a unique ephemeral test passphrase")
                            return True
                        except ValueError:
                            return False
                with patch("app.services.admin.hash_password",return_value="hashed-only"),ThreadPoolExecutor(max_workers=2) as pool:
                    a=pool.submit(initialize,"first-admin");b=pool.submit(initialize,"second-admin")
                    self.assertEqual(sorted([a.result(timeout=15),b.result(timeout=15)]),[False,True])
                with factory() as db:
                    self.assertEqual(db.query(User).count(),1)
                    self.assertEqual(db.query(AdminAuditLog).count(),1)
            finally:
                engine.dispose()
