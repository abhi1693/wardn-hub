import {
  generateServerDetailMetadata,
  generateServerDetailTabStaticParams,
  ServerDetailPageTemplate,
} from "../server-detail-page-template";

export const revalidate = 3600;

type ServerDetailTabPageProps = {
  params: Promise<{ namespace?: string; serverSlug?: string; tab?: string }>;
};

export const generateStaticParams = generateServerDetailTabStaticParams;

export function generateMetadata({ params }: ServerDetailTabPageProps) {
  return generateServerDetailMetadata({ params });
}

export default function ServerDetailTabPage({ params }: ServerDetailTabPageProps) {
  return <ServerDetailPageTemplate params={params} />;
}
