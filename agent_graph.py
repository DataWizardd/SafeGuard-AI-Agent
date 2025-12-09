import os  # <--- [필수 추가] 파일명을 예쁘게 자르기 위해 필요
from typing import TypedDict, List
from langgraph.graph import StateGraph, END
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from rag_setup import get_retriever
from pdf_gen import generate_permit_pdf

# LLM 설정
llm = ChatOpenAI(model="gpt-4o", temperature=0)
retriever = get_retriever()

# --- 1. 상태(State) 정의 ---
class AgentState(TypedDict):
    user_input: str
    messages: List[str]
    context: str
    risk_level: str
    risk_score: int
    final_output: str
    pdf_path: str
    needs_more_info: bool

# --- 2. 노드(Agent) 정의 ---

def coordinator(state: AgentState):
    """사용자 의도 파악 및 정보 누락 확인 (유연한 버전)"""
    print("🤖 [Coordinator] 분석 중...")
    prompt = f"""
    사용자의 입력: "{state['user_input']}"
    
    이 입력이 '작업 허가' 요청인지 판단하고, 다음 필수 정보가 포함되어 있는지 확인해.
    1. **작업 종류** (예: 용접, 청소, 교체, 점검 등)
    2. **장소 및 대상** (예: 3번 탱크, 배관, 제어실 등)
    
    **[판단 기준]**
    - 위 1, 2번 정보가 있으면 **도구(Tool)에 대한 언급이 없더라도 "OK"**라고 답해.
    - 정보가 너무 부족해서 위험성을 판단할 수 없다면 "MISSING"이라고 답해.
    """
    response = llm.invoke([HumanMessage(content=prompt)]).content
    
    if "MISSING" in response:
        return {"needs_more_info": True, "messages": ["작업 장소와 내용을 조금 더 구체적으로 말씀해 주세요."]}
    return {"needs_more_info": False}

def regulation_finder(state: AgentState):
    """RAG를 통해 규정 검색 (출처 파일명 포함)"""
    print("📚 [Regulation Agent] 규정 검색 중...")
    query = state['user_input']
    docs = retriever.invoke(query)
    
    # [수정] 단순 텍스트 결합이 아니라, "파일명 + 내용" 형태로 포맷팅
    formatted_docs = []
    for doc in docs:
        source_path = doc.metadata.get("source", "알 수 없음")
        filename = os.path.basename(source_path) # 경로 떼고 파일명만 추출
        content = doc.page_content
        formatted_docs.append(f"📄 [출처: {filename}]\n{content}")
    
    # 나중에 구분하기 쉽게 구분자(---)로 연결
    context_text = "\n\n---\n\n".join(formatted_docs)
    return {"context": context_text}

def risk_analyst(state: AgentState):
    """Fine-Kinney 알고리즘 기반 정량적 위험성 평가"""
    print("⚠️ [Risk Analyst] 위험도 계산 중 (Fine-Kinney)...")
    
    prompt = f"""
    너는 화학 플랜트 안전 전문가다. 아래 [작업 내용]과 [규정]을 분석하여 'Fine-Kinney 기법'으로 위험성을 정량 평가하라.
    
    [작업 내용]
    {state['user_input']}
    
    [관련 규정 및 물질 정보]
    {state['context']}
    
    [Fine-Kinney 평가 기준표]
    1. 가능성(Probability, P):
       - 10: 예상됨 (거의 확실함)
       - 6: 상당히 가능함
       - 3: 일어날 수 있음 (반반)
       - 1: 거의 없음
       - 0.5: 생각할 수 있으나 가능성 희박
       
    2. 노출빈도(Exposure, E):
       - 10: 연속 노출 (매일)
       - 6: 매일 1회 정도
       - 3: 주 1회 또는 가끔
       - 2: 월 1회 정도
       - 1: 연 몇 회
       - 0.5: 매우 드묾
       
    3. 강도(Consequence, C) - 사고 발생 시 예상 피해:
       - 100: 재난 (다수 사망, 설비 완파)
       - 40: 중대 (사망 1명, 심각한 화재/폭발)
       - 15: 영구 불능 (장애 발생)
       - 7: 중상 (휴업 필요)
       - 3: 경상
       - 1: 경미
       
    [지시사항]
    위 기준에 맞춰 P, E, C 점수를 선정하고, 위험 점수(R = P x E x C)를 계산하라.
    
    [출력 형식] (반드시 이 형식을 지킬 것)
    재해유형: [폭발/화재/질식/중독 중 택1]
    P: [점수]
    E: [점수]
    C: [점수]
    R: [점수]
    평가근거: [30자 내외 요약]
    """
    
    response = llm.invoke([HumanMessage(content=prompt)]).content
    
    # 결과 파싱 (LLM이 준 텍스트에서 숫자만 추출)
    try:
        # 텍스트에서 값을 추출하기 위한 간단한 파싱 로직
        lines = response.split('\n')
        p_score = 0
        e_score = 0
        c_score = 0
        r_score = 0
        accident_type = "알 수 없음"
        
        for line in lines:
            if "P:" in line: p_score = float(line.split(":")[1].strip())
            if "E:" in line: e_score = float(line.split(":")[1].strip())
            if "C:" in line: c_score = float(line.split(":")[1].strip())
            if "R:" in line: r_score = float(line.split(":")[1].strip())
            if "재해유형:" in line: accident_type = line.split(":")[1].strip()
            
        # 등급 판정
        if r_score >= 320: level = "Very High (즉시 중단)"
        elif r_score >= 160: level = "High (긴급 개선)"
        elif r_score >= 70: level = "Medium (개선 필요)"
        else: level = "Low (관리 대상)"
        
        # UI에 보여줄 상세 리포트 생성
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
        print(f"파싱 에러: {e}")
        r_score = 0
        level = "Error"
        final_report = "위험성 평가 중 오류가 발생했습니다."

    # R 점수를 risk_score에 저장 (15점 기준이 아니라 이제 160점 기준으로 로직 변경 필요)
    # 기존 로직과의 호환성을 위해 risk_score 필드는 그대로 두되, 점수 체계가 바뀜을 인지해야 함.
    
    return {"risk_score": int(r_score), "risk_level": level, "context": state['context'] + "\n\n" + final_report}

def admin_agent(state: AgentState):
    """최종 PDF 생성 및 UI용 단문 메시지 작성 (Medium 등급 추가)"""
    print("📝 [Admin Agent] PDF 생성 중...")
    score = state['risk_score']
    context = state['context']
    user_input = state['user_input']
    level = state['risk_level']
    
    # 1. LLM 요약 (그대로 유지)
    reasoning_prompt = f"""
    너는 제조 현장의 깐깐한 안전관리자다.
    아래 [규정 및 정보]를 바탕으로, 사용자의 작업 요청("{user_input}")에 대한 핵심 위험 요인 3가지를 추출해라.
    ... (중략) ...
    """
    reason_summary = llm.invoke([HumanMessage(content=reasoning_prompt)]).content
    
    try:
        pdf_file = generate_permit_pdf(score, level, reason_summary, user_input)
    except Exception as e:
        print(f"PDF 생성 실패: {e}")
        pdf_file = None
    
    # [수정된 부분] 3단계 판정 로직 (High / Medium / Low)
    if score >= 160:
        # High Risk: 무조건 반려
        short_msg = f"🚨 **작업 허가 반려 (위험도 {score}점 / High)**\n\n위험도가 허용 기준을 초과했습니다.\n상세 반려 사유는 첨부된 PDF를 확인하세요."
    
    elif score >= 70:
        # Medium Risk: 조건부 승인 (여기가 핵심!)
        short_msg = f"""
        ⚠️ **조건부 작업 승인 (위험도 {score}점 / Medium)**
        
        작업이 허가되었으나, **추가 안전 조치**가 필수적입니다.
        PDF에 명시된 **[필수 조치 사항]**을 반드시 이행 후 작업하세요.
        """
    else:
        # Low Risk: 바로 승인
        short_msg = f"✅ **작업 허가 승인 (위험도 {score}점 / {level})**\n\n일반 위험 작업으로 승인되었습니다.\n작업 허가서를 다운로드하세요."
        
    return {"final_output": short_msg, "pdf_path": pdf_file}

# --- 3. 그래프 연결 ---
workflow = StateGraph(AgentState)

workflow.add_node("coordinator", coordinator)
workflow.add_node("regulation_finder", regulation_finder)
workflow.add_node("risk_analyst", risk_analyst)
workflow.add_node("admin_agent", admin_agent)

workflow.set_entry_point("coordinator")

def check_info(state):
    return "end" if state['needs_more_info'] else "next"

workflow.add_conditional_edges(
    "coordinator",
    check_info,
    {"end": END, "next": "regulation_finder"}
)

workflow.add_edge("regulation_finder", "risk_analyst")
workflow.add_edge("risk_analyst", "admin_agent")
workflow.add_edge("admin_agent", END)

app_graph = workflow.compile()