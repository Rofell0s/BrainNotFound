"""Voice reading of interview replies (browser speech synthesis)."""
from app import db
from app.models.interview import Interview, InterviewSession


def session_for(interview, user, **kwargs):
    s = InterviewSession(interview_id=interview.id, user_id=user.id, **kwargs)
    db.session.add(s)
    db.session.commit()
    return s


def chat_page(login, user, session):
    return login(user).get(f'/interview/session/{session.get_url_identifier()}/chat').get_data(as_text=True)


def test_mode_decides_whether_the_voice_is_offered(world, content, login):
    interview, learner = content['itw_a'], world['eleve_3a']
    session = session_for(interview, learner)

    interview.tts_mode = Interview.TTS_OFF
    db.session.commit()
    assert 'id="voice-toggle"' not in chat_page(login, learner, session)

    interview.tts_mode = Interview.TTS_OPTIONAL
    db.session.commit()
    assert 'id="voice-toggle"' in chat_page(login, learner, session)


def test_optional_mode_follows_the_learner_preference(world, content, login):
    interview, learner = content['itw_a'], world['eleve_3a']
    interview.tts_mode = Interview.TTS_OPTIONAL
    session = session_for(interview, learner)

    learner.tts_enabled = False
    db.session.commit()
    assert 'startOn: false' in chat_page(login, learner, session)

    learner.tts_enabled = True
    db.session.commit()
    assert 'startOn: true' in chat_page(login, learner, session)


def test_always_mode_starts_on_and_is_not_saved_as_a_preference(world, content, login):
    interview, learner = content['itw_a'], world['eleve_3a']
    interview.tts_mode = Interview.TTS_ALWAYS
    learner.tts_enabled = False  # the interview decides, not the learner
    session = session_for(interview, learner)
    db.session.commit()

    html = chat_page(login, learner, session)
    assert 'startOn: true' in html and 'persist: false' in html


def test_the_toggle_is_remembered_across_devices(world, content, login):
    learner = world['eleve_3a']
    client = login(learner)

    assert client.post('/interview/preferences/voice', json={'enabled': True}).get_json() == {
        'success': True, 'enabled': True}
    assert learner.tts_enabled is True

    client.post('/interview/preferences/voice', json={'enabled': False})
    assert learner.tts_enabled is False


def test_the_toggle_needs_a_login(client):
    assert client.post('/interview/preferences/voice', json={'enabled': True}).status_code in (301, 302)


def test_voice_settings_survive_an_export_and_reimport(world, content, login):
    import io
    import json

    interview = content['itw_a']
    interview.tts_mode = Interview.TTS_ALWAYS
    interview.tts_voice_hint = 'Thomas'
    interview.tts_rate = 0.9
    db.session.commit()

    client = login(world['dir_a'])
    exported = client.get(f'/interview/admin/interviews/{interview.get_url_identifier()}/export-json').get_json()
    assert exported['tts_mode'] == 'always' and exported['tts_voice_hint'] == 'Thomas'
    assert exported['tts_rate'] == 0.9

    client.post('/interview/admin/interviews/import', data={
        'file': (io.BytesIO(json.dumps(exported).encode()), 'itw.json')
    }, content_type='multipart/form-data', follow_redirects=True)

    imported = Interview.query.filter(Interview.id != interview.id, Interview.title == interview.title).first()
    assert imported is not None
    assert imported.get_tts_mode() == 'always'
    assert imported.tts_voice_hint == 'Thomas'
    assert imported.get_tts_rate() == 0.9


def test_an_old_export_imports_as_optional(world, content, login):
    import io
    import json

    client = login(world['dir_a'])
    client.post('/interview/admin/interviews/import', data={
        'file': (io.BytesIO(json.dumps({
            'export_type': 'interview', 'title': 'Sans voix', 'system_prompt': 'p'
        }).encode()), 'old.json')
    }, content_type='multipart/form-data', follow_redirects=True)

    imported = Interview.query.filter_by(title='Sans voix').first()
    assert imported is not None
    assert imported.get_tts_mode() == Interview.TTS_OPTIONAL
    assert imported.get_tts_rate() == 1.0


def test_the_spoken_language_follows_the_interface_language(world, content, login):
    """get_locale() hands templates a plain string: 'fr'.language would silently be undefined."""
    interview, learner = content['itw_a'], world['eleve_3a']
    session = session_for(interview, learner)

    learner.language_preference = 'fr'
    db.session.commit()
    assert 'lang: "fr-FR"' in chat_page(login, learner, session)

    learner.language_preference = 'en'
    db.session.commit()
    assert 'lang: "en-US"' in chat_page(login, learner, session)


def test_the_persona_voice_and_rate_reach_the_page(world, content, login):
    interview, learner = content['itw_a'], world['eleve_3a']
    interview.tts_voice_hint = 'Thomas'
    interview.tts_rate = 0.8
    session = session_for(interview, learner)
    db.session.commit()

    html = chat_page(login, learner, session)
    assert 'hint: "Thomas"' in html and 'rate: 0.8' in html


def test_the_wizard_exposes_the_voice_settings(world, content, login):
    interview = content['itw_a']
    interview.tts_mode = Interview.TTS_ALWAYS
    interview.tts_voice_hint = 'Thomas'
    db.session.commit()

    client = login(world['dir_a'])
    for url in ('/interview/admin/interviews/create',
                f'/interview/admin/interviews/{interview.get_url_identifier()}/edit'):
        html = client.get(url).get_data(as_text=True)
        assert 'name="tts_mode"' in html and 'name="tts_rate"' in html, url
    assert 'value="Thomas"' in html  # the edit page shows the saved voice


def test_the_voice_settings_are_saved_from_the_wizard(world, content, login):
    interview = content['itw_a']
    client = login(world['dir_a'])
    client.post(f'/interview/admin/interviews/{interview.get_url_identifier()}/edit', data={
        'title': interview.title,
        'system_prompt': 'prompt',
        'tts_mode': 'always',
        'tts_voice_hint': 'Amelie',
        'tts_rate': '0.8',
    }, follow_redirects=True)

    assert interview.get_tts_mode() == Interview.TTS_ALWAYS
    assert interview.tts_voice_hint == 'Amelie'
    assert interview.get_tts_rate() == 0.8


def test_the_rate_is_clamped_and_a_bad_mode_falls_back(world, content, login):
    from app.routes.interview import apply_tts_settings

    interview = content['itw_a']
    apply_tts_settings(interview, {'tts_mode': 'loud', 'tts_rate': '9', 'tts_voice_hint': '  '})
    assert interview.tts_mode == Interview.TTS_OPTIONAL
    assert interview.tts_rate == 1.5
    assert interview.tts_voice_hint is None

    apply_tts_settings(interview, {'tts_mode': 'off', 'tts_rate': 'vite'})
    assert interview.tts_mode == Interview.TTS_OFF
    assert interview.tts_rate == 1.0
    assert interview.tts_offered() is False
