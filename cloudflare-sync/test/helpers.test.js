import test from "node:test";
import assert from "node:assert/strict";
import { isNewer, normalizeUsername, validatePassword } from "../src/index.js";

test("账号名只允许约定字符并按小写归一", () => {
  assert.deepEqual(normalizeUsername(" Hanako_27 "), {
    display: "Hanako_27",
    normalized: "hanako_27",
  });
  assert.throws(() => normalizeUsername("中文账号"));
  assert.throws(() => normalizeUsername("ab"));
});

test("密码只检查长度且保留大小写", () => {
  assert.equal(validatePassword("Abcdef12"), "Abcdef12");
  assert.throws(() => validatePassword("short"));
});

test("冲突合并只接受时间更新的记录", () => {
  assert.equal(isNewer("2026-09-03T10:00:01.000Z", "2026-09-03T10:00:00.000Z"), true);
  assert.equal(isNewer("2026-09-03T09:59:59.000Z", "2026-09-03T10:00:00.000Z"), false);
  assert.equal(isNewer("invalid", "2026-09-03T10:00:00.000Z"), false);
});
