"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useId, useState } from "react";

import { MapPicker } from "@/components/MapPicker";
import {
  AddressApiError,
  reverseAddress,
  searchAddress,
  type AddressItem,
  type AddressReverseData,
} from "@/lib/address";

// docs/40 §4.2
export const DEBOUNCE_MS = 300;
export const MIN_QUERY_LENGTH = 2;

const TEXT = {
  noResult: "주소를 조금 더 자세히 입력해 주세요",
  mapHint: "주소로 찾기 어려우면 지도에서 골라 주세요.",
  searchError: "주소를 불러오지 못했어요.",
  reverseError: "위치로 주소를 찾지 못했어요.",
  retry: "다시 시도",
  noParcelAtPoint: "이 지점에서는 필지를 찾지 못했어요. 건물 위를 다시 찍어 주세요.",
  noHistory: "식품 업소 기록 없음",
  noPnu: "이 주소는 필지를 확인하지 못했어요",
  relatedUnknown: "같은 건물의 다른 필지 기록은 확인하지 못했어요.",
  locationDenied: "위치 권한이 꺼져 있어요. 주소를 입력하거나 지도에서 골라 주세요.",
  locationFailed: "현재 위치를 확인하지 못했어요. 주소를 입력하거나 지도에서 골라 주세요.",
} as const;

type GeoState = "checking" | "available" | "hidden";
type Source = "search" | "reverse";

/** 브라우저 Geolocation `PERMISSION_DENIED` */
const PERMISSION_DENIED = 1;

function useDebounced(value: string, delay: number): string {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

/** 위치 권한이 이미 거부됐거나 Geolocation이 없으면 버튼을 숨긴다 */
function useGeolocationState(): [GeoState, (state: GeoState) => void] {
  const [state, setState] = useState<GeoState>("checking");
  useEffect(() => {
    let cancelled = false;
    if (!("geolocation" in navigator)) {
      setState("hidden");
      return;
    }
    const permissions = navigator.permissions;
    if (!permissions?.query) {
      setState("available");
      return;
    }
    permissions.query({ name: "geolocation" }).then(
      (status) => {
        if (!cancelled) setState(status.state === "denied" ? "hidden" : "available");
      },
      () => {
        if (!cancelled) setState("available");
      },
    );
    return () => {
      cancelled = true;
    };
  }, []);
  return [state, setState];
}

export function AddressSearch({ onSelect }: { onSelect: (item: AddressItem) => void }) {
  const inputId = useId();
  const [input, setInput] = useState("");
  const [source, setSource] = useState<Source>("search");
  const [mapOpen, setMapOpen] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [geo, setGeo] = useGeolocationState();
  const term = useDebounced(input.trim(), DEBOUNCE_MS);

  const search = useQuery({
    queryKey: ["address-search", term],
    queryFn: ({ signal }) => searchAddress(term, signal),
    enabled: source === "search" && term.length >= MIN_QUERY_LENGTH,
    retry: false,
  });

  // 좌표 결과는 캐시하지 않는다(카카오 이용 조건, data/README.md) — 쿼리 캐시가 아닌 일회성 요청
  const reverse = useMutation({
    mutationFn: ({ lat, lng }: { lat: number; lng: number }) => reverseAddress(lat, lng),
    gcTime: 0,
  });

  const findByPoint = (lat: number, lng: number) => {
    setSource("reverse");
    setNotice(null);
    reverse.mutate({ lat, lng });
  };

  const findMyLocation = () => {
    setNotice(null);
    navigator.geolocation.getCurrentPosition(
      (position) => findByPoint(position.coords.latitude, position.coords.longitude),
      (error) => {
        if (error.code === PERMISSION_DENIED) {
          setGeo("hidden");
          setNotice(TEXT.locationDenied);
        } else {
          setNotice(TEXT.locationFailed);
        }
      },
    );
  };

  return (
    <section aria-label="주소 검색">
      <label htmlFor={inputId} className="font-bold">
        주소
      </label>
      <input
        id={inputId}
        type="search"
        value={input}
        autoComplete="off"
        placeholder="도로명이나 지번 주소"
        className="border-line min-h-touch mt-1 w-full rounded-lg border px-3"
        onChange={(event) => {
          setInput(event.target.value);
          setSource("search");
        }}
      />
      <div className="mt-2 flex flex-wrap gap-2">
        {geo === "available" && (
          <button
            type="button"
            className="border-line min-h-touch rounded-lg border px-3"
            onClick={findMyLocation}
          >
            현재 위치로 찾기
          </button>
        )}
        <button
          type="button"
          aria-expanded={mapOpen}
          className="border-line min-h-touch rounded-lg border px-3"
          onClick={() => setMapOpen((open) => !open)}
        >
          지도에서 고르기
        </button>
      </div>
      {notice && (
        <p role="status" className="bg-surface mt-2 rounded-lg p-3 text-sm">
          {notice}
        </p>
      )}
      {mapOpen && <MapPicker onPick={findByPoint} />}
      <div className="mt-4" aria-live="polite">
        {source === "search" ? (
          <SearchResults
            term={term}
            loading={search.isFetching && !search.data}
            data={search.data?.items}
            error={search.error}
            onRetry={() => void search.refetch()}
            onSelect={onSelect}
          />
        ) : (
          <ReverseResults
            loading={reverse.isPending}
            data={reverse.data}
            failed={reverse.isError}
            onRetry={() => reverse.variables && reverse.mutate(reverse.variables)}
            onSelect={onSelect}
          />
        )}
      </div>
    </section>
  );
}

function Skeleton() {
  return (
    <div role="status" aria-label="불러오는 중" className="space-y-2">
      {[0, 1, 2].map((n) => (
        <div key={n} className="bg-surface h-12 animate-pulse rounded-lg" />
      ))}
    </div>
  );
}

function ErrorBox({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div role="alert">
      <p>{message}</p>
      <button type="button" className="min-h-touch underline" onClick={onRetry}>
        {TEXT.retry}
      </button>
      <p className="text-muted text-sm">{TEXT.mapHint}</p>
    </div>
  );
}

function SearchResults(props: {
  term: string;
  loading: boolean;
  data: AddressItem[] | undefined;
  error: Error | null;
  onRetry: () => void;
  onSelect: (item: AddressItem) => void;
}) {
  if (props.term.length < MIN_QUERY_LENGTH) return null;
  if (props.loading) return <Skeleton />;
  const rejected = props.error instanceof AddressApiError && props.error.status === 422;
  if (props.error && !rejected) {
    return <ErrorBox message={TEXT.searchError} onRetry={props.onRetry} />;
  }
  if (rejected || (props.data && props.data.length === 0)) {
    return (
      <div>
        <p>{TEXT.noResult}</p>
        <p className="text-muted text-sm">{TEXT.mapHint}</p>
      </div>
    );
  }
  return props.data ? <ResultList items={props.data} onSelect={props.onSelect} /> : null;
}

function ReverseResults(props: {
  loading: boolean;
  data: AddressReverseData | undefined;
  failed: boolean;
  onRetry: () => void;
  onSelect: (item: AddressItem) => void;
}) {
  if (props.loading) return <Skeleton />;
  if (props.failed) return <ErrorBox message={TEXT.reverseError} onRetry={props.onRetry} />;
  if (!props.data) return null;
  if (props.data.pnu === null) return <p>{TEXT.noParcelAtPoint}</p>;
  return <ResultList items={props.data.items} onSelect={props.onSelect} />;
}

function ResultList({
  items,
  onSelect,
}: {
  items: AddressItem[];
  onSelect: (item: AddressItem) => void;
}) {
  return (
    <ul className="divide-line divide-y" aria-label="주소 결과">
      {items.map((item, index) => (
        <li key={`${item.pnu ?? "none"}-${item.road_addr ?? item.jibun_addr}-${index}`}>
          <ResultItem item={item} onSelect={onSelect} />
        </li>
      ))}
    </ul>
  );
}

function ResultItem({
  item,
  onSelect,
}: {
  item: AddressItem;
  onSelect: (item: AddressItem) => void;
}) {
  const selectable = item.pnu !== null;
  const dim = !selectable || item.has_history === false;
  return (
    <div className="py-2">
      <button
        type="button"
        disabled={!selectable}
        className={`min-h-touch w-full text-left ${dim ? "text-muted" : "text-ink"}`}
        onClick={() => onSelect(item)}
      >
        {item.road_addr !== null && <span className="block font-bold">{item.road_addr}</span>}
        <span className="block">{item.jibun_addr}</span>
        {item.building_name && <span className="block text-sm">{item.building_name}</span>}
        {!selectable && <span className="block text-sm">{TEXT.noPnu}</span>}
        {selectable && item.has_history === false && (
          <span className="block text-sm">{TEXT.noHistory}</span>
        )}
      </button>
      {/* null은 "확인 못 함", []은 "확인했고 없음" — 빈 목록처럼 다루지 않는다 (docs/40 §4.2) */}
      {item.related_pnus === null && (
        <p className="text-muted mt-1 text-sm">{TEXT.relatedUnknown}</p>
      )}
    </div>
  );
}
