from src.personal_views import assess, reviewed_records, snapshots


def record(**changes):
    return {"ID":"a", "Title":"Community outreach volunteering", "Category":"Volunteering", "Source excerpt":"", "Priority score":40, "Next action":"Review draft and apply", "Source URL":"https://example.org", **changes}


def profile():
    return {"education":"First-year undergraduate", "evidence":[{"id":"outreach", "text":"Supported outreach", "tags":["outreach"]}]}


def test_unknown_probability_is_not_a_percentage():
    a=assess(record(),profile())
    assert a['Acceptance probability'].startswith('Unknown')
    assert a['CV fit']=='Some evidence match'
    assert 'Supported outreach' in a['CV evidence']


def test_final_year_is_not_recommended_to_first_year():
    a=assess(record(**{'Source excerpt':'Eligible only for final-year students.'}),profile())
    assert a['Next action']=='No application action'
    assert a['CV fit']=='Not suitable now'


def test_personal_approval_does_not_override_eligibility_gate():
    r=record(**{'Next action':'Verify eligibility'})
    a=assess(r,profile())
    assert reviewed_records([r],[a],[{'ID':'a','My decision':'Approve'}])[0]['Next action']=='Verify eligibility'
    assert reviewed_records([r],[a],[])[0]['Next action'].startswith('Complete Personal Review')


def test_reject_and_hold_excluded_and_notes_preserved():
    r=record();a=assess(r,profile())
    for choice in ['Reject','Hold']:
        reviews=[{'ID':'a','My decision':choice,'My notes':'Semester conflict'}]
        assert not snapshots([a],reviews)['Best Opportunities']
        assert snapshots([a],reviews)['Volunteering'][0]['My notes']=='Semester conflict'
        assert reviewed_records([r],[a],reviews)[0]['Next action']=='No application action'


def test_no_evidence_is_not_a_best_recommendation():
    a=assess(record(Title='Accounting internship'),profile())
    assert not snapshots([a],[])['Best Opportunities']


def test_review_upsert_preserves_decision_on_refresh():
    from tests.test_personal import MemoryClient
    from src.sheets_store import SheetsStore
    from src.personal_views import ASSESSMENT_COLUMNS, REVIEW_COLUMNS
    client=MemoryClient();store=SheetsStore(client)
    a=assess(record(),profile())
    store.upsert('Personal Review',[{**a,'My decision':'Hold','My notes':'Exam week'}],REVIEW_COLUMNS)
    store.upsert('Personal Review',[{**a,'Priority':90}],ASSESSMENT_COLUMNS)
    row=store.load('Personal Review')[0]
    assert row['My decision']=='Hold' and row['My notes']=='Exam week'


def test_page_adapter_reads_bounded_bytes():
    from unittest.mock import MagicMock,patch
    from src.personal_sources import fetch
    response=MagicMock();response.iter_content.return_value=[b'<html><body><script>tracking</script><main>'+b'Community volunteering and education. '*10+b'</main></body></html>']
    session=MagicMock();session.get.return_value.__enter__.return_value=response
    with patch('src.personal_sources.requests.Session') as factory:
        factory.return_value.__enter__.return_value=session
        rows=fetch({'kind':'page','url':'https://example.org','name':'Official','title':'Volunteer','primary':True})
    assert rows[0]['primary'] is True
    assert 'tracking' not in rows[0]['raw_text']


def test_restricted_background_is_not_inferred_from_cv():
    r=record(Title="Undergraduate scholarship for U.S. Military Family Dependents", **{"Source excerpt":"Community outreach undergraduate award"})
    a=assess(r,profile())
    assert a['Stage check'].startswith('Restricted eligibility')
    assert not snapshots([a],[])['Best Opportunities']
