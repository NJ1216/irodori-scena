from __future__ import annotations

import unittest
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import server.app  # noqa: F401
from server.modules import cast_sync, constants, project_repository, workspace


class CastLookupSnapshotTests(unittest.TestCase):
    def test_global_reference_file_is_hydrated_from_portable_media_url(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            library_file = root / 'characters.json'
            media_root = root / 'media'
            expected = media_root / 'characters' / 'cast-a' / 'reference.wav'
            library_file.write_text(json.dumps([{
                'id': 'cast-a', 'name': 'A',
                'referenceAudioUrl': '/global-media/characters/cast-a/reference.wav',
                'referenceFile': '/stale-local-data/reference.wav',
            }]), encoding='utf-8')
            with (
                patch.object(constants, 'GLOBAL_CHARACTERS_FILE', library_file),
                patch.object(constants, 'GLOBAL_MEDIA_ROOT', media_root),
                patch.object(workspace, 'ensure_data_root'),
            ):
                character = project_repository.read_global_characters()[0]
        self.assertEqual(character['referenceFile'], str(expected.resolve()))

    def test_one_library_read_for_a_hundred_casts(self):
        library = [{'id': str(index), 'name': 'new', 'audioHash': 'fixed'} for index in range(100)]
        project = {'characters': [{**item, 'name': 'old'} for item in library]}
        with patch.object(project_repository, 'read_global_characters', return_value=library) as read:
            self.assertEqual(len(cast_sync.global_cast_update_candidates(project)), 100)
            read.assert_called_once_with()

    def test_duplicate_ids_match_any_candidate_but_offer_last_name_in_project_order(self):
        library = [
            {'id': 'A', 'name': 'first', 'audioHash': 'same'},
            {'id': 'B', 'name': 'updated B', 'audioHash': 'new'},
            {'id': 'A', 'name': 'last', 'audioHash': 'different'},
        ]
        project = {'characters': [
            {**library[0], 'scope': 'project'},
            {'id': 'B', 'name': 'old', 'audioHash': 'old'},
            {'id': 'A', 'name': 'old', 'audioHash': 'old'},
            {**library[1], 'scope': 'global'},
            {'id': 'missing'}, None,
        ]}
        with patch.object(project_repository, 'read_global_characters', return_value=library):
            self.assertEqual(cast_sync.global_cast_update_candidates(project), [
                {'id': 'B', 'name': 'updated B'}, {'id': 'A', 'name': 'last'},
            ])

    def test_missing_hash_uses_existing_reference_and_missing_file_semantics(self):
        with TemporaryDirectory() as directory:
            reference = Path(directory) / 'reference.wav'
            reference.write_bytes(b'fixed reference')
            character = {'id': 'A', 'name': 'A', 'referenceFile': str(reference)}
            missing = {'id': 'B', 'name': 'B', 'referenceFile': str(reference.with_name('missing.wav'))}
            library = [{**character}, {**missing}]
            with patch.object(project_repository, 'read_global_characters', return_value=library):
                self.assertEqual(cast_sync.global_cast_update_candidates({'characters': [character, missing]}), [])
                library[0]['audioHash'] = 'different'
                self.assertEqual(cast_sync.global_cast_update_candidates({'characters': [character, missing]}),
                                 [{'id': 'A', 'name': 'A'}])

    def test_each_operation_reads_new_library_content(self):
        project = {'characters': [{'id': 'A', 'name': 'old', 'audioHash': 'fixed'}]}
        library = [{**project['characters'][0]}]
        with patch.object(project_repository, 'read_global_characters', side_effect=lambda: library):
            self.assertEqual(cast_sync.global_cast_update_candidates(project), [])
            library = [{**library[0], 'name': 'new'}]
            self.assertEqual(cast_sync.global_cast_update_candidates(project), [{'id': 'A', 'name': 'new'}])
