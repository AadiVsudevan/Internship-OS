"""Evidence-grounded application drafts and deterministic interview preparation.

No model calls, fabricated accomplishments, or claims about official form questions.
Human answers live in separate columns and are never inputs to generated text.
"""
from __future__ import annotations

TYPE_PREP: dict[str, tuple[str, str, str]] = {
    "Internship": ("Why this role, and what would you learn in your first month?", "Explain how revenue, costs and cash flow differ. Walk through a business you understand.", "What would a strong first four weeks look like?"),
    "Research": ("What question would you investigate, and why does it matter?", "Define a hypothesis, dataset, identification strategy and one confounder. Explain correlation versus causation.", "What methods and supervision would the project provide?"),
    "Fellowship": ("What specific change would you work towards during the fellowship?", "Define the problem, stakeholders, proposed work, milestones and evidence of impact.", "How are fellows supported and evaluated?"),
    "Scholarship": ("How would this award change what you can study or contribute?", "Prepare your academic goals, actual funding gap and supporting documents. Use verified financial figures only.", "What costs are covered, and what conditions apply to renewal?"),
    "Competition": ("What is your approach and why is it better than the alternatives?", "Practice defining the problem, assumptions, alternatives, unit economics and a short recommendation.", "Which judging criteria carry the most weight?"),
    "Conference": ("What would you contribute and bring back from this conference?", "Prepare two specific learning goals, three people or topics to engage with, and a follow-up plan.", "Are travel support and student participation available?"),
    "Startup Program": ("Who has the problem, and what evidence shows they want your solution?", "Explain customer discovery, willingness to pay, distribution, unit economics and the smallest useful pilot.", "What founder commitments, equity terms and mentor access apply?"),
    "Leadership": ("Tell us about a time you took responsibility for a group outcome.", "Choose a real example; explain the situation, your decision, conflict handled and observable result.", "What decisions and resources would I be responsible for?"),
    "Exchange": ("Why does this exchange fit your academic plan?", "Map actual course prerequisites, credit transfer, language requirements, funding and return dates.", "How are credits approved and accommodation costs handled?"),
    "Other": ("Why does this opportunity fit your next learning goal?", "Prepare a concrete learning objective, relevant example and realistic availability.", "What would successful participation look like?"),
}


def build_pack(record: dict, profile: dict) -> dict:
    """Build a first draft for one record using only declared profile evidence."""
    title = record["Title"]
    category = record["Category"]
    matches = record.get("Matched interests", "")
    interests = matches or ", ".join(profile["interests"][:2])
    evidence = [e for e in profile.get("evidence", [])
                if set(e.get("tags", [])) & set(profile["interests"])]
    proof = evidence[0]["text"] if evidence else "Add one real example of relevant work before submitting."
    intro = f"My name is {profile['name']}. {profile['education']} My interests include {interests}."
    motivation = (f"I am interested in {title} as a way to explore {interests} through practical work. "
                  "I want to understand how ideas from my studies translate into decisions and outcomes. "
                  "Before submitting, I will add the specific project or programme feature that motivates me and explain my contribution.")
    question, technical, interviewer = TYPE_PREP[category]
    return {
        "ID": record["ID"], "Opportunity": title,
        "Draft application": (
            "WORKING DRAFT — suggested fields, not the official application form.\n\n"
            f"Introduce yourself:\n{intro}\n\nWhy are you applying?\n{motivation}\n\n"
            f"Relevant experience:\n{proof}\n"
            "Add your own action, outcome and lesson; do not invent metrics.\n\n"
            "Confirm before submission: official questions and word limits; CV; contact information; "
            "availability; eligibility; work authorisation; travel/funding needs; requested supporting documents."
        ),
        "Interview prep": (
            f"PREPARATION GUIDE — likely practice topics, not confirmed interview questions.\n"
            f"Opportunity: {title}\nSource evidence: {record.get('Source excerpt', '')[:900]}\n\n"
            f"1. Practise a 60-second introduction using the draft.\n2. {question}\n"
            f"3. Topic preparation: {technical}\n4. Evidence to develop: {proof}\n"
            "5. Prepare a truthful example of teamwork, a setback and something you learned.\n"
            f"6. Ask the interviewer: {interviewer}\n"
            "7. Read the official organisation page and one relevant project before the interview; "
            "note its aim, method and one thoughtful question.\n"
            "20-minute rehearsal: introduction (2), motivation (3), evidence (5), topic exercise (7), questions (3)."
        ),
        "Source URL": record["Source URL"],
        "Evidence used": "; ".join(e["id"] + ": " + e["source"] for e in evidence),
        "Generated at": record["Last refreshed"],
        "Review state": "Needs your review; official form not retrieved",
    }
