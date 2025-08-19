import time
from fastapi import Request, HTTPException
from collections import defaultdict
import asyncio

class RateLimitMiddleware:
    def __init__(self, app, calls: int = 100, period: int = 60):
        self.app = app
        self.calls = calls
        self.period = period
        self.clients = defaultdict(list)
        
    async def __call__(self, request: Request, call_next):
        client_ip = request.client.host
        now = time.time()
        
        # 오래된 요청 기록 제거
        self.clients[client_ip] = [
            req_time for req_time in self.clients[client_ip]
            if req_time > now - self.period
        ]
        
        # Rate limit 체크
        if len(self.clients[client_ip]) >= self.calls:
            raise HTTPException(status_code=429, detail="Rate limit exceeded")
        
        self.clients[client_ip].append(now)
        response = await call_next(request)
        return response