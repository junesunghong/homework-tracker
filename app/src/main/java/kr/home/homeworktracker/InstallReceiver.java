package kr.home.homeworktracker;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageInstaller;
import android.widget.Toast;

/** 설치 세션의 결과를 받는다. 사용자 확인이 필요하면 시스템 설치 화면을 띄운다. */
public class InstallReceiver extends BroadcastReceiver {
    @Override
    @SuppressWarnings("deprecation")
    public void onReceive(Context context, Intent intent) {
        int status = intent.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE);
        if (status == PackageInstaller.STATUS_PENDING_USER_ACTION) {
            Intent confirm = intent.getParcelableExtra(Intent.EXTRA_INTENT);
            if (confirm != null) {
                confirm.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                context.startActivity(confirm);
            }
        } else if (status == PackageInstaller.STATUS_SUCCESS) {
            Toast.makeText(context, "업데이트했습니다", Toast.LENGTH_SHORT).show();
        } else if (status != PackageInstaller.STATUS_FAILURE_ABORTED) {  // 사용자가 [취소]한 경우는 조용히
            String detail = intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE);
            Toast.makeText(context, explain(status, detail), Toast.LENGTH_LONG).show();
        }
    }

    /** 설치 실패를 사람이 할 일로 바꿔 말한다. 원문(INSTALL_FAILED_…)도 뒤에 붙여 둔다. */
    static String explain(int status, String detail) {
        String d = detail == null ? "" : detail;
        String why;
        if (status == PackageInstaller.STATUS_FAILURE_CONFLICT || d.contains("UPDATE_INCOMPATIBLE")
                || d.contains("SIGNATURE")) {
            why = "지금 설치된 앱과 서명 키가 다릅니다(시험용 디버그 빌드였거나 키가 바뀜). 앱을 지우고 새로 설치하세요.";
        } else if (d.contains("VERSION_DOWNGRADE")) {
            why = "서버의 앱이 이 기기보다 옛 버전입니다. 서버 기기의 앱을 먼저 업데이트하세요.";
        } else if (status == PackageInstaller.STATUS_FAILURE_INCOMPATIBLE || d.contains("NO_MATCHING_ABIS")
                || d.contains("OLDER_SDK")) {
            why = "이 기기에서는 쓸 수 없는 앱입니다(안드로이드 7 미만이거나 지원하지 않는 CPU).";
        } else if (status == PackageInstaller.STATUS_FAILURE_STORAGE || d.contains("INSUFFICIENT_STORAGE")) {
            why = "저장 공간이 부족합니다. 공간을 비운 뒤 다시 시도하세요.";
        } else if (status == PackageInstaller.STATUS_FAILURE_BLOCKED) {
            why = "설치가 차단되었습니다. Play 프로텍트 경고라면 [세부정보 더보기] → [무시하고 설치]를 누르세요.";
        } else if (status == PackageInstaller.STATUS_FAILURE_INVALID || d.contains("PARSE")) {
            why = "APK 파일이 손상되었습니다. 다시 업데이트를 눌러 새로 받으세요.";
        } else {
            why = "설치하지 못했습니다.";
        }
        return d.isEmpty() ? why : why + "\n(" + d + ")";
    }
}
