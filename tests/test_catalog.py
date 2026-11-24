from app.main import load_courses

def test_catalog_has_unique_ids_and_required_fields():
    _, courses = load_courses()
    assert len(courses) > 0
    assert len({c['id_oferta'] for c in courses}) == len(courses)
