# Sentinel user_id for valuation tests that write to the real Supabase table.
# Referenced in conftest._purge_valuation_test_rows and in each test module
# that mints a ValuationRunStore row, so all test rows share one owner that the
# session-teardown fixture can DELETE in a single query.
VALUATION_TEST_USER_ID = 9999
