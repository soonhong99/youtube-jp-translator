"""
간단한 회귀 테스트: 1) 1:1 강제 옵션 시 길이/1:1 매핑 보장, 2) 동일 문장 반복 금지
실행 방법(프로젝트 루트에서):
    python backend/services/ai-orchestrator/tests/test_force_one_to_one_sanity.py
네트워크/키 필요 없음. 내부 메서드 모킹으로 동작.
"""
import asyncio
import sys
from pathlib import Path

# src를 파이썬 경로에 추가
SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from agents.translator import TranslatorAgent


class DummyTranslator(TranslatorAgent):
    def __init__(self):
        super().__init__(model_name="dummy", temperature=0.0)
        # 테스트에서 네트워크 호출 방지
        self.chain = None
        self.llm = None
        self.force_one_to_one = True

    async def translate_single(self, japanese_text: str) -> str:
        # 입력을 그대로 식별 가능한 형태로 반환
        return f"KO:{japanese_text}"


async def run_checks():
    agent = DummyTranslator()
    texts = [
        "では早速やってみましょう。",
        "まず1店舗目にご紹介するのは…",
        "学芸大学の中でもかなり雰囲気の良い…",
    ]

    # 1) 1:1 강제 시 길이 동일/매핑 보장
    out = await agent.translate_batch(texts)
    assert len(out) == len(texts), "길이가 일치해야 합니다"
    for src, dst in zip(texts, out):
        assert dst == f"KO:{src}", "각 항목이 1:1로 매핑되어야 합니다"

    # 2) 동일 문장 반복 금지 (간단 검사)
    assert len(set(out)) == len(out), "동일 번역이 반복되면 안 됩니다"

    print("PASS: force_one_to_one length and uniqueness checks")


if __name__ == "__main__":
    asyncio.run(run_checks())
