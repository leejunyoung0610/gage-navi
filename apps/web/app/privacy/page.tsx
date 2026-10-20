import type { Metadata } from "next";

import { MeasureSwitch } from "@/components/MeasureSwitch";
import { MEASURE_KEYS } from "@/lib/measure";

/**
 * 개인정보 안내 (docs/40 §2, docs/60 §5, T-104). 실제로 저장·전송하는 항목과 같아야 한다 —
 * 저장·전송이 바뀌면 같은 PR에서 이 페이지도 고친다. 개인정보 보호법 제30조 제1항 제7호에 맞춰
 * 기기에 저장하는 값·목적·끄는 방법을 적는다. 색인하지 않는다(레이아웃 기본 noindex, docs/40 §9)
 */
export const metadata: Metadata = {
  title: "개인정보 안내",
  description: "가게내비가 기기에 저장하는 값과 서버가 받는 값, 방문 측정을 끄는 방법이에요.",
};

const DEVICE_VALUES: { name: string; keys: string[]; purpose: string; how: string }[] = [
  {
    name: "첫 방문 날짜",
    keys: [MEASURE_KEYS.firstVisit],
    purpose: "처음 온 사람 수와 7일 안에 다시 온 비율을 세려고요.",
    how: "아래 스위치를 켜면 보내지 않아요. 값을 지우려면 브라우저에서 이 사이트의 데이터를 삭제해요.",
  },
  {
    name: "“이미 보냈음” 표시",
    keys: [MEASURE_KEYS.firstSent, MEASURE_KEYS.revisitSent],
    purpose: "같은 브라우저가 첫 방문·재방문으로 두 번 세지지 않게 하려고요.",
    how: "첫 방문 날짜와 같아요.",
  },
  {
    name: "측정 끄기 표시",
    keys: [MEASURE_KEYS.off],
    purpose: "아래 스위치를 켠 상태를 기억하려고요.",
    how: "스위치를 다시 끄면 지워져요.",
  },
  {
    name: "오프라인용 사본",
    keys: [],
    purpose:
      "마지막으로 본 자리 페이지(최대 50개)와 화면을 그리는 파일을 인터넷 연결 없이도 보여 주려고요.",
    how: "브라우저에서 이 사이트의 데이터를 삭제해요.",
  },
];

export default function PrivacyPage() {
  return (
    <main className="max-w-page mx-auto space-y-8 px-4 py-8">
      <header className="space-y-2">
        <h1 className="text-xl font-bold">개인정보 안내</h1>
        <p>
          가게내비는 회원 가입이 없고 이름·연락처·사업장 정보를 받지 않아요. 아래는 이 기기에
          저장하는 값과 서버가 받는 값의 전부예요.
        </p>
      </header>

      <section aria-labelledby="device-title" className="space-y-3">
        <h2 id="device-title" className="font-bold">
          이 기기(브라우저)에 저장하는 값
        </h2>
        <ul className="space-y-3">
          {DEVICE_VALUES.map((value) => (
            <li key={value.name} className="border-line space-y-1 rounded-lg border p-3">
              <p className="font-bold">
                {value.name}
                {value.keys.length > 0 && (
                  <span className="text-muted ml-2 text-sm font-normal break-all">
                    {value.keys.join(", ")}
                  </span>
                )}
              </p>
              <p className="text-sm">목적: {value.purpose}</p>
              <p className="text-sm">끄거나 지우는 방법: {value.how}</p>
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="measure-title" className="space-y-3">
        <h2 id="measure-title" className="font-bold">
          방문 측정과 “도움이 됐나요”
        </h2>
        <ul className="list-disc space-y-1 pl-5">
          <li>
            보내는 것은 이벤트 이름(첫 방문, 7일 안 재방문, 도움이 됐나요 예·아니오)과 날짜뿐이에요.
            기기를 알아볼 수 있는 값, 주소, 보던 페이지는 보내지 않아요.
          </li>
          <li>
            서버는 날짜별 합계만 저장해요. IP 주소와 브라우저 정보(User-Agent)는 저장하지 않아요.
          </li>
          <li>
            자동 프로그램(검색 로봇 등)으로 보이는 브라우저는 이벤트를 보내지 않아요. 이 판단은
            브라우저 안에서만 하고, 브라우저 정보를 서버로 보내지 않아요.
          </li>
        </ul>
        <MeasureSwitch />
      </section>

      <section aria-labelledby="correction-title" className="space-y-2">
        <h2 id="correction-title" className="font-bold">
          정정 요청
        </h2>
        <ul className="list-disc space-y-1 pl-5">
          <li>연락처는 받지 않아요. 내용에 연락처 같은 개인정보를 적지 말아 주세요.</li>
          <li>
            요청 종류, 대상 기록, 처리 결과, 시각은 처리 기록으로 남아요. 적은 내용은 처리한 뒤
            1년이 지나면 지워요. 적은 내용은 로그에 남기지 않아요.
          </li>
        </ul>
      </section>

      <section aria-labelledby="address-title" className="space-y-2">
        <h2 id="address-title" className="font-bold">
          주소 검색과 지도
        </h2>
        <ul className="list-disc space-y-1 pl-5">
          <li>
            검색어는 행정안전부 도로명주소 API로 보내 결과를 받아요. 같은 검색에 빨리 답하려고
            검색어와 결과를 서버 메모리에 최대 24시간 두지만, 누가 검색했는지는 함께 두지 않아요.
            검색어는 로그에 남기지 않아요.
          </li>
          <li>
            “현재 위치로 찾기”와 “지도에서 고르기”는 고른 위치의 좌표를 가게내비 서버를 거쳐 카카오
            API로 보내 주소를 찾아요. 좌표와 결과는 저장하거나 로그에 남기지 않아요.
          </li>
          <li>지도를 보여 줄 때는 브라우저가 카카오 지도에 직접 연결해요.</li>
        </ul>
      </section>

      <section aria-labelledby="access-title" className="space-y-2">
        <h2 id="access-title" className="font-bold">
          접속 기록
        </h2>
        <ul className="list-disc space-y-1 pl-5">
          <li>
            가게내비 API 서버는 접속 기록에 IP 주소를 남기지 않아요. 짧은 시간에 요청이 몰리는 것을
            막으려고 IP 주소를 서버 메모리에 최대 1시간 두었다가 버려요.
          </li>
          <li>
            웹페이지를 전달하는 호스팅 업체는 업체 정책에 따라 접속 기록(IP 주소 등)을 잠시 보관할
            수 있어요. 가게내비는 이 기록을 내려받거나 따로 저장·분석하지 않아요.
          </li>
        </ul>
      </section>
    </main>
  );
}
