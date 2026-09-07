import pytest
import httpx
import uuid
import asyncio

BASE_URL = "http://localhost:8001/api"

@pytest.mark.asyncio
async def test_workflow():
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        # 1. Admin login
        res = await client.post("/auth/login", json={"email": "admin@example.com", "password": "admin1234"})
        assert res.status_code == 200, res.text
        admin_token = res.json()["access_token"]
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        # 2. Create problem
        prob_id = f"test_workflow_{uuid.uuid4().hex[:8]}"
        res = await client.post("/admin/problems", headers=admin_headers, json={
            "id": prob_id,
            "title": "Test Workflow Problem",
            "chapter": 1,
            "description": "Just add two numbers",
            "time_limit": 2.0,
            "memory_limit": 256,
            "is_published": True
        })
        assert res.status_code == 201, res.text

        # 3. Add test cases
        res = await client.post(f"/admin/problems/{prob_id}/testcases", headers=admin_headers, json={
            "input": "1 2\n",
            "expected_output": "3\n",
            "points": 1
        })
        assert res.status_code == 201, res.text

        res = await client.post(f"/admin/problems/{prob_id}/testcases", headers=admin_headers, json={
            "input": "10 20\n",
            "expected_output": "30\n",
            "points": 1
        })
        assert res.status_code == 201, res.text

        # 4. Register new user for submission
        user_email = f"user_{uuid.uuid4().hex[:8]}@example.com"
        res = await client.post("/auth/register", json={
            "username": f"user_{uuid.uuid4().hex[:8]}",
            "email": user_email,
            "password": "password123"
        })
        assert res.status_code == 201, res.text
        user_token = res.json()["access_token"]
        user_headers = {"Authorization": f"Bearer {user_token}"}

        # 5. Submit CORRECT solution
        correct_code = "import sys\nprint(sum(map(int, sys.stdin.read().split())))"
        res = await client.post("/submissions", headers=user_headers, json={
            "problem_id": prob_id,
            "language": "python3",
            "source": correct_code
        })
        assert res.status_code == 201, res.text
        sub_id_correct = res.json()["id"]

        # poll
        for _ in range(30):
            await asyncio.sleep(1)
            res = await client.get(f"/submissions/{sub_id_correct}", headers=user_headers)
            assert res.status_code == 200, res.text
            data = res.json()
            if data["status"] in ("DONE", "ERROR"):
                break
        
        if data["status"] != "DONE":
            pytest.fail(f"Expected DONE, got {data['status']}. Full response: {data}")
        assert data["verdict"] == "AC"

        # 6. Submit WRONG solution
        wrong_code = "import sys\nprint(100)"
        res = await client.post("/submissions", headers=user_headers, json={
            "problem_id": prob_id,
            "language": "python3",
            "source": wrong_code
        })
        assert res.status_code == 201, res.text
        sub_id_wrong = res.json()["id"]

        # poll
        for _ in range(30):
            await asyncio.sleep(1)
            res = await client.get(f"/submissions/{sub_id_wrong}", headers=user_headers)
            assert res.status_code == 200, res.text
            data = res.json()
            if data["status"] in ("DONE", "ERROR"):
                break
        
        assert data["status"] == "DONE"
        assert data["verdict"] == "WA"
