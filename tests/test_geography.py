"""India scope applies before caps, to backlog and to existing records."""
from datetime import date
from src.geography import in_scope
from src.personal_engine import reconcile, build_queues
from src.personal_views import assess, snapshots
from tests.test_personal import profile, candidate, NOW


def india(profile):
    return {**profile, 'geography': {'include_global':False,'india_source_hosts':['www.cry.org'],'location_terms':['India','Bengaluru','Delhi']}}


def test_location_vs_nationality_and_remote(profile):
    p=india(profile)
    assert in_scope(candidate(title='Research internship in India'),p)
    assert in_scope(candidate(title='Finance internship in Bengaluru'),p)
    assert not in_scope(candidate(title='Scholarship for Indian students in London'),p)
    assert not in_scope(candidate(title='Remote worldwide internship'),p)
    assert not in_scope(candidate(url='https://www.cry.org.evil.test',title='Internship'),p)
    assert in_scope(candidate(url='https://www.cry.org/volunteering'),p)


def test_filter_before_cap_and_global_opt_in(profile):
    p=india(profile);p['max_new_per_run']=1
    candidates=[candidate('https://example.org/abroad'),candidate('https://example.org/india',title='Internship in India')]
    rows,added=reconcile(candidates,[],p,NOW)
    assert added==1 and rows[0]['Title']=='Internship in India'
    p['geography']['include_global']=True;p['max_new_per_run']=5
    assert len(reconcile(candidates,[],p,NOW)[0])==2


def test_old_global_records_preserved_but_not_queued_or_shown(profile):
    rows,_=reconcile([candidate()],[],profile,NOW)
    rows[0].update({'Eligibility':'Eligible','Verified deadline':'2026-10-12','Verified application URL':'https://example.org/apply','Notes':'Keep my draft'})
    rows,_=reconcile([],rows,india(profile),NOW)
    assert rows[0]['Notes']=='Keep my draft'
    assert build_queues(rows,india(profile),date(2026,9,16))==([],[])
    views=snapshots([assess(rows[0],india(profile))],[])
    assert all(not values for values in views.values())


def test_indian_city_title_and_scoped_remote_marketplace(profile):
    p=india(profile)
    assert in_scope(candidate(title='Consulting internship, Delhi [Stipend]'),p)
    p['geography']['india_remote_hosts']=['internshala.com']
    c=candidate('https://internshala.com/internship/detail/finance-123')
    c['raw_text']='Location: Work from home. Stipend ₹ 5000 /month'
    assert in_scope(c,p)
    c['url']='https://example.org/worldwide'
    assert not in_scope(c,p)
    c['url']='https://internshala.com/internship/detail/finance-123';c['raw_text']='Location: London. Stipend £ 500 /month'
    assert not in_scope(c,p)
