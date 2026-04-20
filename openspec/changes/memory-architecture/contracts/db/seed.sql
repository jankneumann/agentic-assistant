-- Test fixture data for memory-architecture integration tests

INSERT INTO memory (persona, key, value) VALUES
    ('test-persona', 'active_project', '{"name": "newsletter", "status": "active"}'),
    ('test-persona', 'last_session', '{"role": "researcher", "timestamp": "2026-04-20T10:00:00Z"}');

INSERT INTO preferences (persona, category, key, value, confidence) VALUES
    ('test-persona', 'communication', 'tone', '"concise"', 0.9),
    ('test-persona', 'communication', 'format', '"markdown"', 0.8),
    ('test-persona', 'workflow', 'delegation_style', '"explicit"', 0.7);

INSERT INTO interactions (persona, role, summary, metadata) VALUES
    ('test-persona', 'researcher', 'Found 3 relevant papers on memory architectures', '{"sources": 3}'),
    ('test-persona', 'chief_of_staff', 'Morning briefing: 2 emails, 1 calendar event', '{"emails": 2, "events": 1}'),
    ('test-persona', 'writer', 'Drafted newsletter section on AI agents', '{"word_count": 450}');
