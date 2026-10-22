/* Arnés de pruebas C++ ultraligero compatible con Catch2 para Prig IDE */
#pragma once
#include <iostream>
#include <string>
#include <vector>
#include <functional>
#include <sstream>
#include <exception>

namespace Catch {
    struct TestCase {
        std::string name;
        std::function<void()> func;
    };
    inline std::vector<TestCase>& get_tests() {
        static std::vector<TestCase> tests;
        return tests;
    }
    struct AutoReg {
        AutoReg(const char* name, std::function<void()> f) {
            get_tests().push_back({name, f});
        }
    };
    struct TestFailure {
        std::string msg;
    };

    inline std::string escape_json(const std::string& s) {
        std::ostringstream o;
        for (char c : s) {
            if (c == '"') o << "\\\"";
            else if (c == '\\') o << "\\\\";
            else if (c == '\b') o << "\\b";
            else if (c == '\f') o << "\\f";
            else if (c == '\n') o << "\\n";
            else if (c == '\r') o << "\\r";
            else if (c == '\t') o << "\\t";
            else if ((unsigned char)c <= 0x1f) {}
            else o << c;
        }
        return o.str();
    }
}

#define PRIG_CONCAT_INNER(a, b) a##b
#define PRIG_CONCAT(a, b) PRIG_CONCAT_INNER(a, b)
#define TEST_CASE(name, ...) \
    static void PRIG_CONCAT(_test_fn_, __LINE__)(); \
    static Catch::AutoReg PRIG_CONCAT(_reg_, __LINE__)(name, PRIG_CONCAT(_test_fn_, __LINE__)); \
    static void PRIG_CONCAT(_test_fn_, __LINE__)()

#define SECTION(name)

#define REQUIRE(expr) \
    do { \
        if (!(expr)) { \
            std::ostringstream _oss; \
            _oss << "Fallo en REQUIRE(" #expr ")"; \
            throw Catch::TestFailure{_oss.str()}; \
        } \
    } while(0)

#define REQUIRE_FALSE(expr) \
    do { \
        if (expr) { \
            std::ostringstream _oss; \
            _oss << "Fallo en REQUIRE_FALSE(" #expr ")"; \
            throw Catch::TestFailure{_oss.str()}; \
        } \
    } while(0)

#define CHECK(expr) REQUIRE(expr)
#define CHECK_FALSE(expr) REQUIRE_FALSE(expr)

#define REQUIRE_THROWS(expr) \
    do { \
        bool _threw = false; \
        try { expr; } catch(...) { _threw = true; } \
        if (!_threw) { \
            throw Catch::TestFailure{"Se esperaba una excepción y no se lanzó: " #expr}; \
        } \
    } while(0)

#define REQUIRE_THROWS_AS(expr, type) \
    do { \
        bool _threw_expected = false; \
        try { expr; } catch(const type&) { _threw_expected = true; } catch(...) {} \
        if (!_threw_expected) { \
            throw Catch::TestFailure{"Se esperaba " #type " y no se lanzó: " #expr}; \
        } \
    } while(0)

#ifndef PRIG_NO_MAIN
int main() {
    int total = (int)Catch::get_tests().size();
    int pasados = 0;
    std::string fallos_json = "[";
    bool first = true;
    for (auto& t : Catch::get_tests()) {
        try {
            t.func();
            pasados++;
        } catch (const Catch::TestFailure& f) {
            if (!first) fallos_json += ", ";
            first = false;
            fallos_json += "{\"nombre\": \"" + Catch::escape_json(t.name) + "\", \"mensaje\": \"" + Catch::escape_json(f.msg) + "\", \"tipo\": \"fallo\"}";
        } catch (const std::exception& e) {
            if (!first) fallos_json += ", ";
            first = false;
            fallos_json += "{\"nombre\": \"" + Catch::escape_json(t.name) + "\", \"mensaje\": \"" + Catch::escape_json(e.what()) + "\", \"tipo\": \"error\"}";
        } catch (...) {
            if (!first) fallos_json += ", ";
            first = false;
            fallos_json += "{\"nombre\": \"" + Catch::escape_json(t.name) + "\", \"mensaje\": \"Excepción no controlada\", \"tipo\": \"error\"}";
        }
    }
    fallos_json += "]";
    std::cout << "\n__PRIG_RESULTADO__{\"total\": " << total << ", \"pasados\": " << pasados << ", \"fallos\": " << fallos_json << ", \"error\": null}\n";
    return 0;
}
#endif
