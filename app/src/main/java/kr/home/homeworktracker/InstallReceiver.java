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
        } else if (status == PackageInstaller.STATUS_FAILURE_CONFLICT
                || status == PackageInstaller.STATUS_FAILURE_INCOMPATIBLE) {
            Toast.makeText(context, "서명 키가 달라 덮어 설치할 수 없습니다. 앱을 지우고 새로 설치하세요.",
                    Toast.LENGTH_LONG).show();
        } else if (status != PackageInstaller.STATUS_FAILURE_ABORTED) {
            String msg = intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE);
            Toast.makeText(context, "설치 실패: " + (msg == null ? status : msg), Toast.LENGTH_LONG).show();
        }
    }
}
