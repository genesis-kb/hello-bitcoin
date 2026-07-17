import asyncio
import httpx

async def main():
    async with httpx.AsyncClient() as client:
        # Login
        res = await client.post("http://localhost:8001/api/auth/login", json={
            "email": "admin@example.com",
            "password": "admin1234"
        })
        token = res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        
        # Submit solution for ch01_field_add
        code = """class FieldElement:
    def __init__(self, num, prime):
        self.num = num
        self.prime = prime
    def __add__(self, other):
        return FieldElement((self.num + other.num) % self.prime, self.prime)"""
        
        res = await client.post("http://localhost:8001/api/submissions", headers=headers, json={
            "problem_id": "ch01_field_add",
            "language": "python3",
            "source": code
        })
        sub_id = res.json()["id"]
        print(f"Submitted {sub_id}, polling...")
        
        # Poll
        for _ in range(10):
            await asyncio.sleep(1)
            res = await client.get(f"http://localhost:8001/api/submissions/{sub_id}", headers=headers)
            data = res.json()
            print(data["status"], data.get("verdict"))
            if data["status"] in ("DONE", "ERROR"):
                break

asyncio.run(main())
