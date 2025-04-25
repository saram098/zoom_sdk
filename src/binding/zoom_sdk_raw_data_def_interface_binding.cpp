#include <nanobind/nanobind.h>
#include <nanobind/stl/string.h>
#include <nanobind/trampoline.h>
#include <nanobind/stl/function.h>
#include <nanobind/stl/shared_ptr.h>
#include <nanobind/stl/unique_ptr.h>

#include "zoom_sdk.h"

#include "meeting_service_interface.h"
#include "setting_service_interface.h"
#include "auth_service_interface.h"
#include "meeting_service_components/meeting_ai_companion_interface.h"
#include "meeting_service_components/meeting_recording_interface.h"
#include "meeting_service_components/meeting_audio_interface.h"
#include "meeting_service_components/meeting_reminder_ctrl_interface.h"
#include "meeting_service_components/meeting_breakout_rooms_interface_v2.h"
#include "meeting_service_components/meeting_sharing_interface.h"
#include "meeting_service_components/meeting_chat_interface.h"
#include "meeting_service_components/meeting_smart_summary_interface.h"
#include "meeting_service_components/meeting_configuration_interface.h"
#include "meeting_service_components/meeting_video_interface.h"
#include "meeting_service_components/meeting_inmeeting_encryption_interface.h"
#include "meeting_service_components/meeting_participants_ctrl_interface.h"
#include "meeting_service_components/meeting_waiting_room_interface.h"
#include "meeting_service_components/meeting_webinar_interface.h"
#include "meeting_service_components/meeting_raw_archiving_interface.h"





#include "rawdata/zoom_rawdata_api.h"
#include "rawdata/rawdata_audio_helper_interface.h"
#include "zoom_sdk_raw_data_def.h"

#include <iostream>
#include <functional>
#include <memory>

namespace nb = nanobind;
using namespace ZOOMSDK;

void init_zoom_sdk_raw_data_def_interface_binding(nb::module_ &m) {
    nb::class_<AudioRawData>(m, "AudioRawData")
    .def("GetBuffer", [](AudioRawData& self) -> nb::bytes {
        return nb::bytes(self.GetBuffer(), self.GetBufferLen());
     })
    .def("GetBufferLen", &AudioRawData::GetBufferLen)
    .def("GetSampleRate", &AudioRawData::GetSampleRate)
    .def("GetChannelNum", &AudioRawData::GetChannelNum);  

    nb::class_<YUVRawDataI420>(m, "YUVRawDataI420")
        .def("CanAddRef", &YUVRawDataI420::CanAddRef)
        .def("AddRef", &YUVRawDataI420::AddRef)
        .def("Release", &YUVRawDataI420::Release)
        .def("GetYBuffer", [](YUVRawDataI420& self) -> nb::bytes {
            return nb::bytes(self.GetYBuffer(), self.GetStreamWidth() * self.GetStreamHeight());
        })
        .def("GetUBuffer", [](YUVRawDataI420& self) -> nb::bytes {
            return nb::bytes(self.GetUBuffer(), self.GetStreamWidth() * self.GetStreamHeight() / 4);
        })
        .def("GetVBuffer", [](YUVRawDataI420& self) -> nb::bytes {
            return nb::bytes(self.GetVBuffer(), self.GetStreamWidth() * self.GetStreamHeight() / 4);
        })
        .def("GetAlphaBuffer", [](YUVRawDataI420& self) -> nb::bytes {
            return nb::bytes(self.GetAlphaBuffer(), self.GetAlphaBufferLen());
        })
        .def("GetBuffer", [](YUVRawDataI420& self) -> nb::bytes {
            return nb::bytes(self.GetBuffer(), self.GetBufferLen());
        })
        .def("GetBufferLen", &YUVRawDataI420::GetBufferLen)
        .def("GetAlphaBufferLen", &YUVRawDataI420::GetAlphaBufferLen)
        .def("IsLimitedI420", &YUVRawDataI420::IsLimitedI420)
        .def("GetStreamWidth", &YUVRawDataI420::GetStreamWidth)
        .def("GetStreamHeight", &YUVRawDataI420::GetStreamHeight)
        .def("GetRotation", &YUVRawDataI420::GetRotation)
        .def("GetSourceID", &YUVRawDataI420::GetSourceID);
}