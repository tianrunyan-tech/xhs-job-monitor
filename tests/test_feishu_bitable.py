import unittest

from scripts.adapters.feishu_bitable import FeishuBitableAdapter


class FakeFeishu(FeishuBitableAdapter):
    def __init__(self):
        super().__init__({"app_id": "a", "app_secret": "b", "app_token": "app", "table_id": "tbl"})
        self.records = []

    def list_records(self, filter_expr=None):
        if filter_expr and 'note_id' in filter_expr:
            note_id = filter_expr.split('"')[1]
            return [record for record in self.records if record["fields"].get("note_id") == note_id]
        return list(self.records)

    def create_record(self, fields):
        self.records.append({"record_id": f"rec_{len(self.records)+1}", "fields": fields})
        return {}

    def update_record(self, record_id, fields):
        for record in self.records:
            if record["record_id"] == record_id:
                record["fields"].update(fields)
                return {}
        raise AssertionError("record not found")

    def delete_record(self, record_id):
        self.records = [record for record in self.records if record["record_id"] != record_id]
        return {}


class FeishuTests(unittest.TestCase):
    def test_upsert_updates_existing(self):
        adapter = FakeFeishu()
        adapter.create_record({"note_id": "n1"})
        result = adapter.upsert_by_note_id("n1", {"note_id": "n1", "title": "new"})
        self.assertEqual(result, "updated")
        self.assertEqual(adapter.records[0]["fields"]["title"], "new")

    def test_delete_record(self):
        adapter = FakeFeishu()
        adapter.create_record({"note_id": "n1"})
        adapter.delete_record("rec_1")
        self.assertEqual(adapter.records, [])


if __name__ == "__main__":
    unittest.main()
