"""HTML card extraction preserves employers and location without fake eligibility."""
from unittest.mock import MagicMock,patch
from src.personal_sources import fetch


def test_cards_keep_distinct_employers_location_and_cap():
    body=''.join(f'<article><a class="role" href="/job/{i}">Research</a><b class="employer">Firm {i}</b><span class="location">Work from home</span>₹ 5000</article>' for i in range(3))
    response=MagicMock();response.iter_content.return_value=[body.encode()]
    session=MagicMock();session.get.return_value.__enter__.return_value=response
    source={'url':'https://example.org','name':'Test','kind':'html','list_selector':'article','title_selector':'.role','link_selector':'.role','employer_selector':'.employer','location_selector':'.location','title_suffix':' internship','max_items':2}
    with patch('src.personal_sources.requests.Session') as factory:
        factory.return_value.__enter__.return_value=session
        rows=fetch(source)
    assert len(rows)==2
    assert rows[0]['title']=='Research internship at Firm 0'
    assert rows[1]['title']=='Research internship at Firm 1'
    assert rows[0]['raw_text'].startswith('Location: Work from home.')
    assert rows[0]['primary'] is False
