import { HomeAddressSearch } from "@/components/HomeAddressSearch";

export default function HomePage() {
  return (
    <main className="max-w-page mx-auto px-4 py-10">
      <h1 className="text-2xl font-bold">가게내비</h1>
      <p className="text-muted mt-2">계약할 자리의 주소를 찾아 보세요.</p>
      <div className="mt-6">
        <HomeAddressSearch />
      </div>
    </main>
  );
}
