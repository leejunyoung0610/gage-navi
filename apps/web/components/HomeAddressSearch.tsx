"use client";

import { useRouter } from "next/navigation";

import { AddressSearch } from "@/components/AddressSearch";

/** 홈의 주소 검색(docs/40 §4.1). 고른 필지의 페이지(`/place/[pnu]`, T-033)로 간다 */
export function HomeAddressSearch() {
  const router = useRouter();
  return (
    <AddressSearch
      onSelect={(item) => {
        if (item.pnu !== null) router.push(`/place/${item.pnu}`);
      }}
    />
  );
}
