import { describe, expect, it } from "vitest";

import { createProfileStore, PROFILE_STORAGE_KEY, type Profile } from "@/lib/profile-store";

// 가상 예시 프로필 (서울 광진구 코드 형식만 맞춘 값)
const PROFILE: Profile = { schema_version: 1, region: { sido_code: "11", sigungu_code: "11215" } };

function memoryStorage() {
  const items = new Map<string, string>();
  return {
    items,
    getItem: (key: string) => items.get(key) ?? null,
    setItem: (key: string, value: string) => void items.set(key, value),
    removeItem: (key: string) => void items.delete(key),
  };
}

function throwingStorage() {
  const fail = () => {
    throw new DOMException("막힘 (가상 예시)", "SecurityError");
  };
  return { getItem: fail, setItem: fail, removeItem: fail };
}

describe("profile-store", () => {
  it("저장·읽기·삭제", () => {
    const storage = memoryStorage();
    const store = createProfileStore(() => storage);

    expect(store.load()).toBeNull();
    expect(store.save(PROFILE)).toBe(true);
    expect(JSON.parse(storage.items.get(PROFILE_STORAGE_KEY) ?? "null")).toEqual(PROFILE);
    expect(store.load()).toEqual(PROFILE);

    expect(store.clear()).toBe(true);
    expect(storage.items.has(PROFILE_STORAGE_KEY)).toBe(false);
    expect(store.load()).toBeNull();
  });

  it("키는 gn.profile.v1", () => {
    expect(PROFILE_STORAGE_KEY).toBe("gn.profile.v1");
  });

  it("다른 탭·이전 방문에서 저장한 값을 읽는다", () => {
    const storage = memoryStorage();
    storage.setItem(PROFILE_STORAGE_KEY, JSON.stringify(PROFILE));
    expect(createProfileStore(() => storage).load()).toEqual(PROFILE);
  });

  it("모름(null)과 묻지 않음(필드 없음)을 구분해 그대로 둔다", () => {
    const store = createProfileStore(() => memoryStorage());
    const unknown: Profile = { schema_version: 1, region: { sido_code: "11", sigungu_code: null } };
    store.save(unknown);
    expect(store.load()).toEqual(unknown);

    store.save({ schema_version: 1 });
    expect(store.load()).toEqual({ schema_version: 1 });
  });

  it.each([
    ["JSON이 아님", "{"],
    ["버전이 다름", JSON.stringify({ schema_version: 2 })],
    ["코드 형식이 다름", JSON.stringify({ schema_version: 1, region: { sigungu_code: "광진구" } })],
  ])("저장값이 잘못되면(%s) null", (_, raw) => {
    const storage = memoryStorage();
    storage.setItem(PROFILE_STORAGE_KEY, raw);
    expect(createProfileStore(() => storage).load()).toBeNull();
  });

  it("형식이 틀린 프로필은 저장하지 않는다", () => {
    const storage = memoryStorage();
    const store = createProfileStore(() => storage);
    expect(() => store.save({ schema_version: 1, region: { sido_code: "서울" } })).toThrow();
    expect(storage.items.size).toBe(0);
  });

  describe("localStorage 예외", () => {
    it("접근할 때마다 예외가 나도 저장·읽기·삭제가 이 탭 안에서 동작한다", () => {
      const store = createProfileStore(() => throwingStorage());
      expect(store.load()).toBeNull();
      expect(store.save(PROFILE)).toBe(false);
      expect(store.load()).toEqual(PROFILE);
      expect(store.clear()).toBe(false);
      expect(store.load()).toBeNull();
    });

    it("localStorage 속성을 읽는 것 자체가 예외여도 동작한다", () => {
      const store = createProfileStore(() => {
        throw new DOMException("막힘 (가상 예시)", "SecurityError");
      });
      expect(store.save(PROFILE)).toBe(false);
      expect(store.load()).toEqual(PROFILE);
      expect(store.clear()).toBe(false);
      expect(store.load()).toBeNull();
    });

    it("저장 공간이 꽉 차 쓰기만 실패해도 읽기는 메모리 값으로", () => {
      const storage = memoryStorage();
      const store = createProfileStore(() => ({
        ...storage,
        setItem: () => {
          throw new DOMException("가득 참 (가상 예시)", "QuotaExceededError");
        },
      }));
      expect(store.save(PROFILE)).toBe(false);
      expect(store.load()).toEqual(PROFILE);
    });

    it("저장소가 없으면(서버 렌더링) 메모리만", () => {
      const store = createProfileStore(() => undefined);
      expect(store.save(PROFILE)).toBe(false);
      expect(store.load()).toEqual(PROFILE);
    });
  });
});
