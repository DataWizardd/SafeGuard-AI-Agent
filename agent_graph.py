import os
import re
from typing import TypedDict, List
from langgraph.graph import StateGraph, END
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from rag_setup import get_retriever
from pdf_gen import generate_permit_pdf

# LLM 설정
llm = ChatOpenAI(model="gpt-4o", temperature=0)
retriever = get_retriever()


# --- 프롬프트 로더 함수 ---
def load_prompt(filename, **kwargs):
    """
    prompts 폴더의 md 파일을 읽어서 변수({key})를 채워주는 함수
    """
    file_path = os.path.join("prompts", filename)
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
            # 파일 내용에 변수값 주입 (format 사용)
            return content.format(**kwargs)
    except Exception as e:
        print(f"❌ 프롬프트 로드 실패 ({filename}): {e}")
        return ""


# --- 1. 상태(State) 정의 ---
class AgentState(TypedDict):
    user_input: str
    chat_history: str
    messages: List[str]
    context: str
    risk_level: str
    risk_score: int
    final_output: str
    pdf_path: str
    needs_more_info: bool


# --- 2. 노드(Agent) 정의 ---


def coordinator(state: AgentState):
    """Main Orchestrator: 의도 파악 및 정보 병합"""
    print("🤖 [Coordinator] 지능형 분석 중...")

    # [수정] 파일에서 프롬프트 로드
    prompt = load_prompt(
        "coordinator.md",
        chat_history=state.get("chat_history", "없음"),
        user_input=state["user_input"],
    )

    response = llm.invoke([HumanMessage(content=prompt)]).content

    if response.startswith("MISSING"):
        question = response.replace("MISSING:", "").strip()
        return {"needs_more_info": True, "messages": [question]}

    return {"needs_more_info": False}


def regulation_finder(state: AgentState):
    print("📚 [Regulation Agent] 스마트 하이브리드 검색 수행 중...")

    current_input = state["user_input"]
    history = state.get("chat_history", "")
    # 대화 기록과 현재 입력을 합쳐서 전체 맥락 파악
    full_context = f"{history} {current_input}"

    # ---------------------------------------------------------
    # [1] 화학물질 정밀 타겟팅 (파일명 필터링)
    # ---------------------------------------------------------
    target_chemicals = ["톨루엔", "벤젠", "아세톤", "황산", "염산", "수소", "질소"]
    detected_chem = ""

    # 문맥 전체에서 화학물질 감지
    for chem in target_chemicals:
        if chem in full_context:
            detected_chem = chem
            break

    docs_msds = []
    if detected_chem:
        print(f"🎯 화학물질 감지: {detected_chem} -> 파일명 일치 문서만 선별")
        q_msds = f"{detected_chem} MSDS 물질안전보건자료 경고표지"
        raw_msds_docs = retriever.invoke(q_msds)

        # 검색된 문서 중 파일명에 실제 '물질명'이 포함된 것만 남김
        for doc in raw_msds_docs:
            filename = os.path.basename(doc.metadata.get("source", ""))
            if detected_chem in filename:
                docs_msds.append(doc)

    # ---------------------------------------------------------
    # [2] 사내 규정 (S-Chem) 독립 검색
    # ---------------------------------------------------------
    print("🏢 사내 규정(S-Chem) 검색")
    q_sop = "S Chem Safety Regulation_v2 사내 안전 작업 허가 지침 절차"
    docs_sop = retriever.invoke(q_sop)

    # ---------------------------------------------------------
    # [3] 법령 및 가이드 (상황별 키워드 주입)
    # ---------------------------------------------------------
    if any(keyword in full_context for keyword in ["탱크", "밀폐", "청소", "맨홀"]):
        print("🕳️ 밀폐공간/탱크 작업 감지 -> 기술지침 검색 강화")
        q_gen = f"밀폐공간 작업 프로그램 수립 및 시행에 관한 기술지침 {current_input}"
    else:
        print("⚖️ 일반 법령 검색")
        q_gen = f"산업안전보건법 안전 보건 규칙 {current_input}"

    docs_gen = retriever.invoke(q_gen)

    # ---------------------------------------------------------
    # [4] 결과 병합 (우선순위: MSDS -> SOP -> 법령)
    # ---------------------------------------------------------
    combined_docs = []

    # 1순위: 필터링된 MSDS
    if docs_msds:
        combined_docs.extend(docs_msds[:2])

    # 2순위: 사내 규정 (SOP)
    if docs_sop:
        combined_docs.extend(docs_sop[:2])

    # 3순위: 법령/기술지침
    if docs_gen:
        combined_docs.extend(docs_gen[:3])

    # ---------------------------------------------------------
    # [5] 중복 제거
    # ---------------------------------------------------------
    seen_sources = set()
    unique_docs = []

    for doc in combined_docs:
        source = os.path.basename(doc.metadata.get("source", "unknown"))
        if source not in seen_sources:
            seen_sources.add(source)
            unique_docs.append(doc)

    # 최종 6개 문서 선정
    final_docs = unique_docs[:6]

    # [디버깅] 최종 선정된 문서 목록 출력
    print("🔍 [최종 선정 문서 목록]")
    for d in final_docs:
        print(f"   - {os.path.basename(d.metadata.get('source'))}")

    if not final_docs:
        return {"context": "관련 규정을 찾을 수 없습니다."}

    # 컨텍스트 문자열 생성
    formatted_docs = []
    for doc in final_docs:
        filename = os.path.basename(doc.metadata.get("source", "파일_없음"))
        content = doc.page_content.strip()
        formatted_docs.append(f"📄 [출처: {filename}]\n{content}")

    context_text = "\n\n---\n\n".join(formatted_docs)
    return {"context": context_text}


def risk_analyst(state: AgentState):
    """Fine-Kinney 알고리즘 기반 정량적 위험성 평가"""
    print("⚠️ [Risk Analyst] 위험도 계산 중 (Fine-Kinney)...")

    # 파일에서 프롬프트 로드
    prompt = load_prompt(
        "risk_analyst.md",
        chat_history=state.get("chat_history", "없음"),
        user_input=state["user_input"],
        context=state["context"],
    )

    response = llm.invoke([HumanMessage(content=prompt)]).content

    try:
        # 정규표현식 파싱
        p_match = re.search(r"P\s*[:=]\s*([\d\.]+)", response)
        e_match = re.search(r"E\s*[:=]\s*([\d\.]+)", response)
        c_match = re.search(r"C\s*[:=]\s*([\d\.]+)", response)
        r_match = re.search(r"R\s*[:=]\s*([\d\.]+)", response)

        p_score = float(p_match.group(1)) if p_match else 0
        e_score = float(e_match.group(1)) if e_match else 0
        c_score = float(c_match.group(1)) if c_match else 0

        if r_match:
            r_score = float(r_match.group(1))
        else:
            r_score = p_score * e_score * c_score

        type_match = re.search(r"재해유형\s*[:=]\s*(.+)", response)
        accident_type = type_match.group(1).strip() if type_match else "복합 위험"

        if r_score >= 320:
            level = "Very High"
        elif r_score >= 160:
            level = "High"
        elif r_score >= 70:
            level = "Medium"
        else:
            level = "Low"

        final_report = f"""
**🎯 Fine-Kinney 위험성 평가 결과**
* **재해 형태:** {accident_type}
* **계산 공식:** $Risk = P \\times E \\times C$
* **상세 점수:**
    * 가능성(P): **{p_score}**
    * 노출빈도(E): **{e_score}**
    * 강도(C): **{c_score}**
* **최종 위험도(R):** <span style='color:red; font-size:1.2em; font-weight:bold;'>{int(r_score)}점</span> ({level})
"""
    except Exception as e:
        print(f"파싱 에러: {e} / LLM 응답: {response}")
        r_score = 0
        level = "Error"
        final_report = "위험성 평가 데이터를 추출할 수 없습니다."

    return {
        "risk_score": int(r_score),
        "risk_level": level,
        "context": state["context"] + "\n\n" + final_report,
    }


def admin_agent(state: AgentState):
    """최종 PDF 생성 및 메시지 작성 (프롬프트 파일 분리 버전)"""
    print("📝 [Admin Agent] 작업 내용 요약 및 PDF 생성 중...")

    score = state["risk_score"]
    context = state["context"]
    history = state.get("chat_history", "")
    last_input = state["user_input"]

    # ------------------------------------------------------------------
    # [STEP 1] 대화 기록을 바탕으로 '통합 작업 내용' 요약하기
    # ------------------------------------------------------------------
    summary_prompt = load_prompt(
        "work_summary.md", history=history, last_input=last_input
    )

    # 만약 파일 로드 실패 시 대비용 안전장치
    if not summary_prompt:
        summary_prompt = f"대화기록: {history}\n마지막입력: {last_input}\n위 내용을 포함해 작업 내용을 한 문장으로 요약해."

    # 작업 제목을 LLM이 다시 씁니다.
    consolidated_work_info = (
        llm.invoke([HumanMessage(content=summary_prompt)])
        .content.replace('"', "")
        .strip()
    )
    print(f"📌 통합된 작업 내용: {consolidated_work_info}")

    # ------------------------------------------------------------------
    # [STEP 2] 위험 요인 분석
    # ------------------------------------------------------------------
    # admin_agent.md 파일 로드
    reasoning_prompt_content = load_prompt(
        "admin_agent.md",
        user_input=consolidated_work_info,
        context=context,
    )

    reason_summary = llm.invoke(
        [HumanMessage(content=reasoning_prompt_content)]
    ).content

    # ------------------------------------------------------------------
    # [STEP 3] PDF 생성
    # ------------------------------------------------------------------
    try:
        # 요약된 작업 내용(consolidated_work_info)을 PDF 제목으로 전달
        pdf_file = generate_permit_pdf(
            score, state["risk_level"], reason_summary, consolidated_work_info
        )
    except Exception as e:
        print(f"PDF 에러: {e}")
        pdf_file = None

    # UI 메시지 생성
    if score >= 160:
        short_msg = f"🚨 **반려 (High Risk / {score}점)**\n상세 사유는 PDF 확인 필요."
    elif score >= 70:
        short_msg = (
            f"⚠️ **조건부 승인 (Medium Risk / {score}점)**\n안전 조치 이행 후 작업 가능."
        )
    else:
        short_msg = f"✅ **승인 (Low Risk / {score}점)**\n작업 허가서 발급 완료."

    return {"final_output": short_msg, "pdf_path": pdf_file}


# --- 3. 그래프 연결 ---
workflow = StateGraph(AgentState)
workflow.add_node("coordinator", coordinator)
workflow.add_node("regulation_finder", regulation_finder)
workflow.add_node("risk_analyst", risk_analyst)
workflow.add_node("admin_agent", admin_agent)
workflow.set_entry_point("coordinator")


def check_info(state):
    return "end" if state["needs_more_info"] else "next"


workflow.add_conditional_edges(
    "coordinator", check_info, {"end": END, "next": "regulation_finder"}
)
workflow.add_edge("regulation_finder", "risk_analyst")
workflow.add_edge("risk_analyst", "admin_agent")
workflow.add_edge("admin_agent", END)

app_graph = workflow.compile()
