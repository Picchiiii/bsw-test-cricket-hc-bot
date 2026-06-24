import os
import httpx
from dotenv import load_dotenv

load_dotenv()

class TursoDB:
    def __init__(self):
        self.url = os.getenv("TURSO_DATABASE_URL")
        self.token = os.getenv("TURSO_AUTH_TOKEN")
        self.url = self.url.replace("libsql://", "https://")
        self.url = self.url.replace("wss://", "https://")
        self.client = httpx.AsyncClient(
            timeout=10.0,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json"
            }
        )   

    async def close(self):
        await self.client.aclose()

    async def execute(self, sql: str, args: list | None = None):
        payload = {
            "requests": [
                {
                    "type": "execute",
                    "stmt": {
                        "sql": sql,
                        "args": args or []
                    }
                }
            ]
        }

        response = await self.client.post(
            f"{self.url}/v2/pipeline",
            json=payload
        )

        response.raise_for_status()
        return response.json()


    async def fetch(self, sql: str, args: list | None = None):
        res = await self.execute(sql, args)
        try:
            return res["results"][0]["response"]["result"]["rows"]
        except:
            return []


    async def init_db(self):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(base_dir, "schemas.sql"), "r", encoding="utf-8") as f:
            schemas = f.read()

        statements = [s.strip() for s in schemas.split(";") if s.strip()]

        for stmt in statements:
            await self.execute(stmt)


    async def init_match(self, match_data: dict):
        sql = """
        INSERT INTO ongoing_matches (channel_id,
                                    team_A_score,
                                    team_B_score,
                                    match_state,
                                    match_settings,
                                    match_stats,)
        VALUES (?, ?, ?, ?, ?, ?)
        """