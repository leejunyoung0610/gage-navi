/**
 * 사업장 프로필 — 이 기기의 `localStorage`에만 둔다 (ADR-014: 서버 저장·로그 금지).
 *
 * - 키 `gn.profile.v1`, `schema_version` 1. T-061은 optional 필드만 더하므로 이 시점에 저장한 값이 그대로 유효하다
 * - 필드는 docs/21 §3 이름을 따른다. 값이 `null`이면 "모름"(UNKNOWN), 필드가 없으면 아직 묻지 않음
 * - `localStorage` 접근은 전부 try/catch. 막혀 있으면(사파리 개인 정보 보호 모드, 저장 공간 초과 등) 이 탭의
 *   메모리에만 두고 화면은 그대로 동작한다
 */
import { z } from "zod";

export const PROFILE_STORAGE_KEY = "gn.profile.v1";

export const profileSchema = z.object({
  schema_version: z.literal(1),
  region: z
    .object({
      sido_code: z
        .string()
        .regex(/^\d{2}$/)
        .nullable()
        .optional(),
      sigungu_code: z
        .string()
        .regex(/^\d{5}$/)
        .nullable()
        .optional(),
    })
    .optional(),
});

export type Profile = z.infer<typeof profileSchema>;

/** 저장소 접근자. `localStorage` 속성을 읽는 것만으로 예외가 나는 브라우저가 있어 함수로 받는다 */
export type StorageGetter = () => Pick<Storage, "getItem" | "setItem" | "removeItem"> | undefined;

export interface ProfileStore {
  /** 저장된 프로필. 없거나 형식이 맞지 않으면 `null` */
  load(): Profile | null;
  /** 저장한다. 기기 저장에 성공하면 `true`, 메모리에만 남았으면 `false` */
  save(profile: Profile): boolean;
  /** 이 기기에서 지운다. 기기 저장소까지 지웠으면 `true` */
  clear(): boolean;
}

function parse(raw: string | null): Profile | null {
  if (raw === null) return null;
  try {
    const result = profileSchema.safeParse(JSON.parse(raw));
    return result.success ? result.data : null;
  } catch {
    return null;
  }
}

export function createProfileStore(getStorage: StorageGetter): ProfileStore {
  // 기기 저장이 막혔을 때의 대체 저장소 (이 탭이 살아 있는 동안만)
  let memory: Profile | null = null;

  return {
    load() {
      try {
        const storage = getStorage();
        if (storage) return parse(storage.getItem(PROFILE_STORAGE_KEY)) ?? memory;
      } catch {
        // 아래 메모리 값으로
      }
      return memory;
    },
    save(profile) {
      const valid = profileSchema.parse(profile);
      memory = valid;
      try {
        const storage = getStorage();
        if (!storage) return false;
        storage.setItem(PROFILE_STORAGE_KEY, JSON.stringify(valid));
        return true;
      } catch {
        return false;
      }
    },
    clear() {
      memory = null;
      try {
        const storage = getStorage();
        if (!storage) return false;
        storage.removeItem(PROFILE_STORAGE_KEY);
        return true;
      } catch {
        return false;
      }
    },
  };
}

/** 앱이 쓰는 기본 저장소. 서버 렌더링 중에는 `localStorage`가 없어 메모리만 쓴다 */
export const profileStore = createProfileStore(() =>
  typeof window === "undefined" ? undefined : window.localStorage,
);
