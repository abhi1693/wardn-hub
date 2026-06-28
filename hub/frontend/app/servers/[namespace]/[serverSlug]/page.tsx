import {
  generateServerDetailMetadata,
  generateServerDetailOverviewStaticParams,
  ServerDetailPageTemplate,
} from "./server-detail-page-template";

export const revalidate = 3600;

type ServerDetailPageProps = {
  params: Promise<{ namespace?: string; serverSlug?: string }>;
};

export const generateStaticParams = generateServerDetailOverviewStaticParams;

export function generateMetadata({ params }: ServerDetailPageProps) {
  return generateServerDetailMetadata({ fixedTab: "overview", params });
}

export default function ServerDetailPage({ params }: ServerDetailPageProps) {
  return <ServerDetailPageTemplate fixedTab="overview" params={params} />;
}
