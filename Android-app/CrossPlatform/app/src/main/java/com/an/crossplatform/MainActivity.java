package com.an.crossplatform;

import android.Manifest;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.content.pm.PackageInfo;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.provider.Settings;
import android.util.Log;
import android.widget.Button;
import android.widget.ImageButton;

import androidx.annotation.NonNull;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.app.ActivityCompat;

import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import android.content.Context;
import android.app.AlertDialog;
import android.net.ConnectivityManager;
import android.net.NetworkInfo;
import android.widget.Toast;


public class MainActivity extends AppCompatActivity {

    private static final int REQUEST_CODE_STORAGE_PERMISSION = 1;
    private static final int REQUEST_CODE_MANAGE_STORAGE_PERMISSION = 2;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        FileLogger.init(this);
        getVersionName();
        requestStoragePermissions();

        createConfigFileIfNotExists();
        //createdownloadfolder();


        Button btnSend = findViewById(R.id.btn_send);
        Button btnReceive = findViewById(R.id.btn_receive);
        ImageButton btnPreferences = findViewById(R.id.btn_preferences);

        btnSend.setOnClickListener(v -> {
            if (!shouldShowWarning()) {
                if (!isWifiConnected()) {
                    showNetworkWarning("Please connect to a Wifi-network before sending files.", true, null);
                    return;
                }
                startActivity(new Intent(MainActivity.this, DiscoverDevicesActivity.class));
                return;
            }

            if (!isWifiConnected()) {
                showNetworkWarning("Please connect to a Wifi-network before sending files.", true, null);
                return;
            }

            showNetworkWarning(
                    "Before starting the transfer, please ensure both the sender and receiver devices are connected to the same network.",
                    false,
                    () -> startActivity(new Intent(MainActivity.this, DiscoverDevicesActivity.class))
            );
        });

        btnReceive.setOnClickListener(v -> {
            if (!shouldShowWarning()) {
                if (!isWifiConnected()) {
                    showNetworkWarning("Please connect to a Wifi-network before receiving files.", true, null);
                    return;
                }
                startActivity(new Intent(MainActivity.this, WaitingToReceiveActivity.class));
                return;
            }

            if (!isWifiConnected()) {
                showNetworkWarning("Please connect to a Wifi-network before receiving files.", true, null);
                return;
            }

            showNetworkWarning(
                    "Before starting the transfer, please ensure both the sender and receiver devices are connected to the same network.",
                    false,
                    () -> startActivity(new Intent(MainActivity.this, WaitingToReceiveActivity.class))
            );
        });

        btnPreferences.setOnClickListener(v -> {
            Intent intent = new Intent(MainActivity.this, PreferencesActivity.class);
            startActivity(intent);
        });
    }

    private String getVersionName() {
        try {
            // Fetch version name from the app's PackageInfo
            PackageInfo packageInfo = getPackageManager().getPackageInfo(getPackageName(), 0);
            String versionName = packageInfo.versionName;

            // Log the version name
            FileLogger.log("AppVersion", "Version Name: " + versionName);

            return versionName;
        } catch (PackageManager.NameNotFoundException e) {
            e.printStackTrace();
            FileLogger.log("AppVersion", "Version Name not found", e);
            return "Unknown";
        }

    }

    private void requestStoragePermissions() {
        if (!Environment.isExternalStorageManager()) {
            AlertDialog.Builder builder = new AlertDialog.Builder(this);
            builder.setTitle("Permission Required")
                    .setMessage("This app needs access to manage all files on your device to save the transferred files. Please grant the permission by clicking the grant button then allowing access to the app.")
                    .setPositiveButton("Grant Permission", (dialog, which) -> {
                        Intent intent = new Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION,
                                Uri.parse("package:" + getPackageName()));
                        startActivityForResult(intent, REQUEST_CODE_MANAGE_STORAGE_PERMISSION);
                    })
                    .setNegativeButton("Cancel", (dialog, which) -> {
                        dialog.dismiss();
                        Toast.makeText(this, "Storage permission is required. App will close.",
                                Toast.LENGTH_SHORT).show();
                        finish();
                    })
                    .setCancelable(false)
                    .show();
        }
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, @NonNull String[] permissions, @NonNull int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);

        if (requestCode == REQUEST_CODE_STORAGE_PERMISSION) {
            // Check if permissions are granted
            if (grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
                Toast.makeText(this, "Storage permission granted", Toast.LENGTH_SHORT).show();
            } else {
                Toast.makeText(this, "Storage permission denied", Toast.LENGTH_SHORT).show();
            }
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);

        if (requestCode == REQUEST_CODE_MANAGE_STORAGE_PERMISSION) {
            if (Environment.isExternalStorageManager()) {
                Toast.makeText(this, "All files access granted", Toast.LENGTH_SHORT).show();
            } else {
                Toast.makeText(this, "All files access permission denied. App will close.",
                        Toast.LENGTH_SHORT).show();
                finish();
            }
        }
    }

    private void createConfigFileIfNotExists() {
        try {
            File configDir = new File(Environment.getExternalStorageDirectory(), "Android/media/" + getPackageName() + "/Config");
            FileLogger.log("MainActivity", "Config directory path: " + configDir.getAbsolutePath());

            if (!configDir.exists()) {
                boolean folderCreated = configDir.mkdirs();
                if (!folderCreated) {
                    FileLogger.log("MainActivity", "Failed to create config directory");
                    return;
                }
            }

            File file = new File(configDir, "config.json");
            String currentVersion = getVersionName();
            String existingDeviceName = Build.MODEL;
            String existingSaveToDirectory = null;
            boolean existingEncryption = false;
            boolean shouldCreateFile = !file.exists();

            // Read existing config if it exists
            if (file.exists()) {
                try {
                    String content = new String(java.nio.file.Files.readAllBytes(file.toPath()));
                    JSONObject existingConfig = new JSONObject(content);
                    String configVersion = existingConfig.optString("json_version", "");

                    if (configVersion.equals(currentVersion)) {
                        FileLogger.log("MainActivity", "Config file is up to date.");
                        return;
                    }

                    // Preserve existing values
                    existingDeviceName = existingConfig.optString("device_name", Build.MODEL);
                    existingSaveToDirectory = existingConfig.optString("saveToDirectory", null);
                    existingEncryption = existingConfig.optBoolean("encryption", false);
                    shouldCreateFile = true;

                    FileLogger.log("MainActivity", "Config version mismatch. Updating config file.");
                } catch (Exception e) {
                    FileLogger.log("MainActivity", "Error reading existing config", e);
                    shouldCreateFile = true;
                }
            }

            if (shouldCreateFile) {
                if (file.exists()) {
                    file.delete();
                }
                boolean fileCreated = file.createNewFile();
                if (fileCreated) {
                    JSONObject jsonObject = new JSONObject();

                    // Set up default save directory if not preserved from existing config
                    if (existingSaveToDirectory == null) {
                        File mediaDir = new File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS), "DataDash");
                        if (!mediaDir.exists()) {
                            boolean dirCreated = mediaDir.mkdirs();
                            if (!dirCreated) {
                                FileLogger.log("MainActivity", "Failed to create media directory");
                                return;
                            }
                        }
                        existingSaveToDirectory = mediaDir.getAbsolutePath();
                        if (existingSaveToDirectory.startsWith("/storage/emulated/0")) {
                            existingSaveToDirectory = existingSaveToDirectory.replace("/storage/emulated/0", "");
                        }
                    }

                    // Create JSON with preserved/default values
                    jsonObject.put("json_version", currentVersion);
                    jsonObject.put("device_name", existingDeviceName);
                    jsonObject.put("saveToDirectory", existingSaveToDirectory);
                    jsonObject.put("maxFileSize", 1000000);
                    jsonObject.put("encryption", existingEncryption);
                    jsonObject.put("show_warn", true);
                    jsonObject.put("auto_check", true);

                    try (FileOutputStream fileOutputStream = new FileOutputStream(file)) {
                        fileOutputStream.write(jsonObject.toString().getBytes());
                        FileLogger.log("MainActivity", "Config file created/updated successfully.");
                    }
                } else {
                    FileLogger.log("MainActivity", "Failed to create config.json");
                }
            }
        } catch (Exception e) {
            FileLogger.log("MainActivity", "Error creating or writing to config.json", e);
        }
    }

    private boolean shouldShowWarning() {
        try {
            File configFile = new File(Environment.getExternalStorageDirectory(),
                    "Android/media/" + getPackageName() + "/Config/config.json");
            if (configFile.exists()) {
                String content = new String(java.nio.file.Files.readAllBytes(configFile.toPath()));
                JSONObject config = new JSONObject(content);
                return config.optBoolean("show_warn", true);
            }
        } catch (Exception e) {
            FileLogger.log("MainActivity", "Error reading show_warn from config", e);
        }
        return true;
    }

    private boolean isWifiConnected() {
        ConnectivityManager cm = (ConnectivityManager) getSystemService(Context.CONNECTIVITY_SERVICE);
        if (cm == null) return false;

        Network activeNetwork = cm.getActiveNetwork();
        if (activeNetwork == null) return false;

        NetworkCapabilities capabilities = cm.getNetworkCapabilities(activeNetwork);
        if (capabilities == null) return false;

        return capabilities.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) &&
                capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET) &&
                capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED);
    }

    private void showNetworkStatusDialog(String message, boolean isError, Runnable onPositive) {
        if (!shouldShowWarning()) {
            if (onPositive != null) onPositive.run();
            return;
        }

        new AlertDialog.Builder(this)
                .setTitle("Warning")
                .setMessage(message)
                .setPositiveButton("OK", (dialog, which) -> {
                    dialog.dismiss();
                    if (!isError && onPositive != null) {
                        onPositive.run();
                    }
                })
                .show();
    }

    private void startActivityWithNetworkCheck(Class<?> destinationActivity) {
        if (!shouldShowWarning()) {
            startActivity(new Intent(MainActivity.this, destinationActivity));
            return;
        }

        if (!isWifiConnected()) {
            showNetworkStatusDialog("Please connect to a network before proceeding.", true, null);
            return;
        }

        showNetworkStatusDialog(
                "Before starting the transfer, please ensure both the sender and receiver devices are connected to the same network.",
                false,
                () -> startActivity(new Intent(MainActivity.this, destinationActivity))
        );
    }

    private void showNetworkWarning(String message, boolean isNoConnection, Runnable onContinue) {
        if (!shouldShowWarning()) {
            if (onContinue != null) onContinue.run();
            return;
        }

        new AlertDialog.Builder(this)
                .setTitle("Warning")
                .setMessage(message)
                .setPositiveButton("OK", (dialog, which) -> {
                    dialog.dismiss();
                    if (!isNoConnection && onContinue != null) {
                        onContinue.run();
                    }
                })
                .show();
    }


//    private void createdownloadfolder() {
//        try {
//            // Set up the path to the Downloads/DataDash directory
//            File downloadDir = new File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS), "DataDash");
//            FileLogger.log("MainActivity", "DataDash download directory path: " + downloadDir.getAbsolutePath());
//
//            // Create the DataDash directory if it doesn't exist
//            if (!downloadDir.exists()) {
//                boolean folderCreated = downloadDir.mkdirs();
//                if (!folderCreated) {
//                    FileLogger.log("MainActivity", "Failed to create DataDash download directory");
//                    return;
//                } else {
//                    FileLogger.log("MainActivity", "DataDash download directory created successfully");
//                }
//            } else {
//                FileLogger.log("MainActivity", "DataDash download directory already exists");
//            }
//
//        } catch (Exception e) {
//            FileLogger.log("MainActivity", "Error creating DataDash download directory", e);
//        }
//    }

}