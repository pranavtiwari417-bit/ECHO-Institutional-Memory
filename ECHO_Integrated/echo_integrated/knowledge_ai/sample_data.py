"""Synthetic (fictional) college documents used by the tests and the example script.

All names, dates and decisions are invented. The sentences use plain active-voice
minutes so that MOCK mode can parse them; real Gemma extraction handles freer text.
"""

from typing import List

from .schemas import SourceDocument

COUNCIL_PAGE_1 = """ACADEMIC COUNCIL MINUTES

The Academic Council of Riverside College met on March 5, 2024. Dr. Meera Iyer chaired the meeting. Attendees included Prof. Arjun Rao, Dr. Sunita Verma and Prof. Kabir Mehta.

On March 5, 2024, Prof. Arjun Rao proposed the introduction of the BSc in Data Science program. The Academic Council approved the introduction of the BSc in Data Science program on March 5, 2024 because student demand for analytics courses has doubled since 2022.

To implement this decision, the Computer Science Department was tasked with preparing the curriculum by June 30, 2024. Dr. Sunita Verma is a member of the Computer Science Department."""

COUNCIL_PAGE_2 = """ANY OTHER BUSINESS

On March 5, 2024, the Academic Council deferred the proposal to revise the examination schedule because the Examination Cell has not submitted its report."""

BOARD_PAGE_1 = """BOARD OF GOVERNORS MINUTES

The Board of Governors of Riverside College met on April 2, 2024. Dr. Rahul Menon chaired the meeting. Dr. Meera Iyer presented the recommendation of the Academic Council.

The Board of Governors approved the BSc in Data Science program on April 2, 2024 because the program aligns with the college strategic plan and the projected enrolment is sufficient.

The Department of Student Affairs was responsible for updating the admissions brochure by July 15, 2024."""

FINANCE_PAGE_1 = """FINANCE COMMITTEE MINUTES

The Finance Committee met on March 20, 2024. Prof. Kabir Mehta chaired the meeting.

The Finance Committee rejected the purchase of new laboratory equipment on March 20, 2024 because the annual equipment budget was already exhausted."""

SAMPLE_DOCUMENTS: List[SourceDocument] = [
    SourceDocument(
        document_id="DOC-001",
        filename="academic_council_minutes_2024-03-05.txt",
        pages=[COUNCIL_PAGE_1, COUNCIL_PAGE_2],
    ),
    SourceDocument(
        document_id="DOC-002",
        filename="board_of_governors_minutes_2024-04-02.txt",
        pages=[BOARD_PAGE_1],
    ),
    SourceDocument(
        document_id="DOC-003",
        filename="finance_committee_minutes_2024-03-20.txt",
        pages=[FINANCE_PAGE_1],
    ),
]

SAMPLE_QUESTIONS = [
    "Why was the BSc in Data Science program approved?",
    "What was decided on April 2, 2024?",
    "Why did the Finance Committee reject the laboratory equipment purchase?",
    "What is the hostel fee policy for 2025?",
]
