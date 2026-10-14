import Link from "next/link";

// docs/40 §3: 서비스명, 메뉴(자리 이력 · 정책자금 · 폐업 지원 · 내 사업장)
const MENU = [
  { href: "/", label: "자리 이력" },
  { href: "/funding", label: "정책자금" },
  { href: "/closure", label: "폐업 지원" },
  { href: "/profile", label: "내 사업장" },
] as const;

export function SiteHeader() {
  return (
    <header className="border-line border-b">
      <div className="max-w-page mx-auto px-4">
        <Link
          href="/"
          className="text-brand-strong min-h-touch inline-flex items-center text-xl font-bold"
        >
          가게내비
        </Link>
        <nav aria-label="주 메뉴">
          <ul className="-mx-2 flex flex-wrap">
            {MENU.map((item) => (
              <li key={item.href}>
                <Link
                  href={item.href}
                  className="text-ink hover:text-brand-strong min-h-touch inline-flex items-center px-2"
                >
                  {item.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
      </div>
    </header>
  );
}
