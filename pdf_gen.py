import os
import textwrap
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from datetime import datetime

# 한글 폰트 등록
try:
    pdfmetrics.registerFont(TTFont('Malgun', 'C:/Windows/Fonts/Malgun.ttf'))
    font_name = 'Malgun'
except:
    font_name = 'Helvetica'

def draw_footer(c, width):
    c.setLineWidth(0.5)
    c.line(50, 40, 545, 40)
    c.setFont(font_name, 8)
    c.drawCentredString(width / 2, 25, "본 문서는 SafeGuard-AI 시스템에 의해 자동 생성되었습니다.")

def generate_permit_pdf(risk_score, risk_level, reason_summary, user_input):
    
    if not os.path.exists("./outputs"):
        os.makedirs("./outputs")
    
    filename = f"./outputs/Permit_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    c = canvas.Canvas(filename, pagesize=A4)
    width, height = A4

    current_y = height - 50 

    # [수정된 부분] 1. 점수에 따른 3단계 제목 및 색상 설정
    c.setFont(font_name, 20)
    
    if risk_score >= 160:  # High Risk (반려)
        c.setFillColorRGB(1, 0, 0) # 빨간색
        title = "❌ 작업 허가 반려 통보서"
    elif risk_score >= 70: # Medium Risk (조건부 승인)
        c.setFillColorRGB(1, 0.5, 0) # 주황색
        title = "⚠️ 조건부 작업 허가서 (조치 필요)"
    else:                  # Low Risk (승인)
        c.setFillColorRGB(0, 0.5, 0) # 초록색
        title = "✅ 일반 작업 허가서 (Hot Work Permit)"
    
    c.drawCentredString(width / 2, current_y, title)
    current_y -= 40

    # 2. 기본 정보
    c.setFillColorRGB(0, 0, 0)
    c.setFont(font_name, 11)
    
    c.drawString(50, current_y, f"발행 일시: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    current_y -= 20

    input_prefix = "신청 작업: "
    full_input = input_prefix + user_input
    wrapped_input = textwrap.wrap(full_input, width=65)
    
    for line in wrapped_input:
        c.drawString(50, current_y, line)
        current_y -= 15
    
    current_y -= 20

    # 3. 위험성 평가 결과 박스
    box_top = current_y
    box_height = 70
    
    c.setLineWidth(1)
    # 위험 등급에 따라 박스 테두리 색상도 맞춤 (선택사항)
    if risk_score >= 160: c.setStrokeColorRGB(1, 0, 0)
    elif risk_score >= 70: c.setStrokeColorRGB(1, 0.5, 0)
    else: c.setStrokeColorRGB(0, 0.5, 0)
    
    c.rect(50, box_top - box_height, 500, box_height, stroke=1, fill=0)
    c.setStrokeColorRGB(0, 0, 0) # 다시 검은색 복귀
    
    c.setFont(font_name, 12)
    c.drawString(70, box_top - 25, "위험성 평가 결과 (Risk Assessment)")
    c.setFont(font_name, 11)
    c.drawString(70, box_top - 50, f"위험 점수: {risk_score}점  |  위험 등급: {risk_level}")
    
    current_y -= (box_height + 40)

    # 4. 상세 분석 의견
    c.setFont(font_name, 12)
    c.drawString(50, current_y, "상세 분석 및 조치 사항")
    current_y -= 25
    
    c.setFont(font_name, 10)
    clean_summary = reason_summary.replace('**', '').replace('##', '').replace('__', '')
    paragraphs = clean_summary.split('\n')
    
    for paragraph in paragraphs:
        if not paragraph.strip():
            continue
            
        wrapped_lines = textwrap.wrap(paragraph, width=65)
        
        for line in wrapped_lines:
            if current_y < 60:
                draw_footer(c, width)
                c.showPage()
                c.setFont(font_name, 10)
                current_y = height - 50
                c.drawString(50, current_y, "(다음 장에서 계속)")
                current_y -= 20
            
            c.drawString(50, current_y, line)
            current_y -= 15
        
        current_y -= 8

    draw_footer(c, width)
    c.save()
    return filename